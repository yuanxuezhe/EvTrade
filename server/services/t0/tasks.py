"""
t0_tasks.py — T0Task 业务逻辑层 (REQ-TRADE-013 ~ 015 + 017)

提供：
- create_task / list_tasks / get_task_detail / update_task / delete_task
- balance_task: 按 task 净敞口配平到 base_volume + target_volume
- close_task: 强制配平到 base_volume 后关闭 task
- aggregate_task_stats: 统计 (realized/unrealized/win_rate/trading_days)
- list_overview: 整体做T收益 (cross-task summary)
- list_overview_by_stock: 单券做T收益 (per-stock summary)

设计原则：
- 所有跨日查询走 orders.task_id IS NOT NULL 过滤（不复用 user_def='T0' 路径）
- 旧 user_def='T0' AND task_id=NULL 的单保持兼容：通过 get_task_stats?include_legacy=true 聚合
- 持仓/资产前置校验走 REQ-TRADE-010 同款 409 Conflict
"""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from server.models.orm import Asset, Order, Position, T0Task, Trade
from server.services.t0.core import get_fee_config, round_to_lot
from server.services.t0.pnl import calc_realized_pnl
from server.services.t0.fees import _q2, _q4, calc_commission_and_tax
import logging

log = logging.getLogger(__name__)


# ───────────────────── CRUD ─────────────────────

def create_task(
    db: Session,
    user_id: int,
    stock_code: str,
    base_volume: int = 0,
    target_volume: int = 0,
    coefficient: float = 1.0,
    note: Optional[str] = None,
    created_trd_date: Optional[str] = None,
) -> T0Task:
    """创建 T0Task.

    Args:
        base_volume: 底仓量 (>= 0)
        target_volume: 目标开仓量 (可为负=净减仓)
        coefficient: 配平系数
        note: 备注
        created_trd_date: 创建日交易日；None 时取 db 当前激活日

    Returns:
        新建的 T0Task (db.refresh 后, 含 id)
    """
    if base_volume < 0:
        raise ValueError("base_volume 必须 >= 0")
    if not (0.0 <= coefficient <= 10.0):
        raise ValueError("coefficient 必须在 [0, 10]")

    if not created_trd_date:
        from server.models.orm import SysStatus
        sys_row = db.query(SysStatus).filter_by(status='active').first()
        created_trd_date = sys_row.trd_date if sys_row else datetime.now().strftime("%Y%m%d")

    task = T0Task(
        user_id=user_id,
        stock_code=stock_code,
        base_volume=base_volume,
        target_volume=target_volume,
        coefficient=coefficient,
        note=note,
        status='active',
        created_trd_date=created_trd_date,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    log.info(f"[T0Task] created id={task.id} user={user_id} stock={stock_code} "
             f"base={base_volume} target={target_volume}")
    return task


def list_tasks(
    db: Session,
    user_id: int,
    is_admin: bool = False,
    status: Optional[str] = None,
    stock_code: Optional[str] = None,
    days: Optional[int] = None,
) -> List[Dict]:
    """列表 task (带 summary).

    trader 仅看自己的 task (user_id 过滤)；admin 看所有
    按 created_at DESC 排序
    每行附带 summary: {task_net_volume, realized_pnl, unrealized_pnl, position_vol}
    """
    q = db.query(T0Task)
    if not is_admin:
        q = q.filter(T0Task.user_id == user_id)
    if status:
        q = q.filter(T0Task.status == status)
    if stock_code:
        q = q.filter(T0Task.stock_code == stock_code)
    if days:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        q = q.filter(T0Task.created_trd_date >= cutoff)

    tasks = q.order_by(T0Task.created_at.desc()).all()
    result = []
    for t in tasks:
        summary = _compute_summary(db, t)
        result.append({**{c.name: getattr(t, c.name) for c in t.__table__.columns}, **summary})
    return result


def get_task_detail(db: Session, task_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict]:
    """获取 task 详情. 无权限或不存在返回 None."""
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return None
    if not is_admin and t.user_id != user_id:
        return None
    summary = _compute_summary(db, t)
    return {**{c.name: getattr(t, c.name) for c in t.__table__.columns}, **summary}


def update_task(
    db: Session, task_id: int, user_id: int,
    is_admin: bool = False,
    note: Optional[str] = None,
    coefficient: Optional[float] = None,
    target_volume: Optional[int] = None,
    status: Optional[str] = None,
) -> Optional[T0Task]:
    """更新 task. status 仅允许 active ↔ closed 切换 (archived 由 DELETE 路径产生)."""
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return None
    if not is_admin and t.user_id != user_id:
        return None

    if note is not None:
        t.note = note
    if coefficient is not None:
        if not (0.0 <= coefficient <= 10.0):
            raise ValueError("coefficient 必须在 [0, 10]")
        t.coefficient = coefficient
    if target_volume is not None:
        t.target_volume = target_volume

    if status is not None and status != t.status:
        # active ↔ closed 双向切换；不允许直接 → archived (DELETE 路径做)
        if status not in ('active', 'closed'):
            raise ValueError(f"status 仅允许 active/closed, 不能直转 {status}")
        if t.status == 'archived':
            raise ValueError("archived 状态不能改")
        t.status = status
        if status == 'closed' and not t.closed_at:
            t.closed_at = datetime.utcnow()
        elif status == 'active':
            t.closed_at = None

    db.commit()
    db.refresh(t)
    return t


def delete_task(db: Session, task_id: int, user_id: int, is_admin: bool = False) -> bool:
    """删除 task. active/closed 可删 (误建可立即删); archived 视为长期记录不允许硬删.
    同时 set orders.task_id = NULL.
    """
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return False
    if not is_admin and t.user_id != user_id:
        return False
    if t.status == 'archived':
        raise ValueError(f"archived 状态不允许硬删 (请保留做长期记录), 当前 {t.status}")

    # 关联 orders.task_id 置 NULL (保留审计)
    db.query(Order).filter(Order.task_id == task_id).update({"task_id": None})
    db.delete(t)
    db.commit()
    return True


def archive_task(db: Session, task_id: int, user_id: int, is_admin: bool = False) -> Optional[T0Task]:
    """归档 task. closed → archived 状态切换."""
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return None
    if not is_admin and t.user_id != user_id:
        return None
    if t.status != 'closed':
        raise ValueError(f"仅 closed 状态可归档, 当前 {t.status}")
    t.status = 'archived'
    db.commit()
    db.refresh(t)
    return t


# ───────────────────── 配平 (REQ-TRADE-014 + 017) ─────────────────────

def balance_task(
    db: Session,
    task_id: int,
    user_id: int,
    is_admin: bool = False,
) -> Dict:
    """一键配平.

    Returns:
        {
          'action': 'BUY' | 'SELL' | 'NONE',
          'volume': int,
          'price': float (当前最新价；前端可改),
          'reason': str,
          'task_target_position': int,
          'current_position_vol': int,
          'task_net_volume': int,
          'balance_volume': int (整手后)
        }
    """
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return {'action': 'NONE', 'volume': 0, 'reason': 'task 不存在'}
    if not is_admin and t.user_id != user_id:
        return {'action': 'NONE', 'volume': 0, 'reason': '无权限'}
    if t.status != 'active':
        return {'action': 'NONE', 'volume': 0, 'reason': f'task 状态 {t.status}, 不允许配平'}

    # 1. 计算 task 净敞口 (跨日累加)
    task_net_volume = _calc_task_net_volume(db, task_id)

    # 2. 取当前持仓
    pos = db.query(Position).filter_by(stock_code=t.stock_code).first()
    current_position_vol = int(pos.vol) if pos else 0
    current_position_avl = int(pos.avl_vol) if pos else 0

    # 3. 目标仓位 = base_volume + target_volume
    task_target_position = int(t.base_volume) + int(t.target_volume)

    # 4. 缺口 = target - position (正=要买, 负=要卖)
    gap = task_target_position - current_position_vol

    # 5. 应用配平系数 (>= 1.0 默认全平)
    coefficient = float(t.coefficient)
    balanced_volume = round(gap * coefficient)

    # 6. 整手 (按方向: 买向下, 卖向上)
    if balanced_volume > 0:
        action = 'BUY'
        balance_volume = round_to_lot(balanced_volume, 'BUY')
    elif balanced_volume < 0:
        action = 'SELL'
        balance_volume = -round_to_lot(-balanced_volume, 'SELL')
        # 但卖不能超持仓可用
        balance_volume = max(balance_volume, -current_position_avl)
    else:
        action = 'NONE'
        balance_volume = 0

    # 7. 资金校验 (买单)
    if action == 'BUY' and balance_volume > 0:
        asset = db.query(Asset).first()
        cash = float(asset.cash) if asset else 0.0
        price = _last_price(db, t.stock_code)
        cost = balance_volume * price
        if cost > cash:
            raise ValueError(
                f"资金不足, 需 ¥{_q2(cost)} 现有 ¥{_q2(cash)}"
            )

    # 8. 持仓校验 (卖单)
    if action == 'SELL' and -balance_volume > current_position_avl:
        raise ValueError(
            f"持仓不足, 缺 {int(-balance_volume - current_position_avl)} 股"
        )

    return {
        'action': action,
        'volume': abs(balance_volume),
        'direction_volume': balance_volume,  # 正数=买, 负数=卖
        'price': _last_price(db, t.stock_code),
        'reason': _balance_reason(task_net_volume, current_position_vol, task_target_position, action),
        'task_target_position': task_target_position,
        'current_position_vol': current_position_vol,
        'task_net_volume': task_net_volume,
    }


def close_task(db: Session, task_id: int, user_id: int, is_admin: bool = False) -> Dict:
    """关 task: 先配平到 base_volume (保留底仓), 再改 status=closed.

    Returns:
        {'task': T0Task, 'balance_result': Dict}
    """
    # 先配平: 临时把 target_volume 设为 0, 这样 balance 会算到 base_volume
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        raise ValueError("task 不存在")
    if not is_admin and t.user_id != user_id:
        raise ValueError("无权限")
    if t.status != 'active':
        raise ValueError(f"task 状态 {t.status}, 不允许关")

    original_target = t.target_volume
    t.target_volume = 0
    db.commit()
    try:
        balance_result = balance_task(db, task_id, user_id, is_admin)
    finally:
        t.target_volume = original_target
        db.commit()

    # 不管 balance 配了多少, 关 task
    t.status = 'closed'
    t.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(t)

    return {'task': _task_to_dict(t), 'balance_result': balance_result}


# ───────────────────── 统计 (REQ-TRADE-015) ─────────────────────

def aggregate_task_stats(db: Session, task_id: int) -> Dict:
    """task 维度统计: realized + unrealized + win_rate + trading_days + daily[]

    v62 (REQ-TRADE-022): realized_pnl 算法改为按 Order 委托口径
      - 已成交部分: 用 Order.price (委托价)
      - 未成交部分: 买入用 ask1_price (卖一价), 卖出用 bid1_price (买一价)
      - 配平后: (avg_sell - avg_buy) * paired_vol - fee - tax
    """
    t = db.query(T0Task).filter(T0Task.id == task_id).first()
    if not t:
        return {}

    fee_cfg = get_fee_config()

    # v62: 取 task 内所有 Order (跨日累积, 不限 trd_date)
    orders = db.query(Order).filter(
        Order.task_id == task_id,
    ).all()

    # v62: 取最新 ask1/bid1 (兜底配平价)
    from server.models.orm import QuoteSnapshot
    snap = db.query(QuoteSnapshot).filter_by(stock_code=t.stock_code).order_by(QuoteSnapshot.ts.desc()).first()
    ask1 = float(snap.ask1_price or 0) if snap and snap.ask1_price else 0.0
    bid1 = float(snap.bid1_price or 0) if snap and snap.bid1_price else 0.0

    # v62: 按 Order 委托口径算 effective buy/sell vol + amt
    # 已成交部分用 Order.price, 未成交部分按方向用 bid1/ask1
    eff_buy_vol, eff_buy_amt = 0, 0.0
    eff_sell_vol, eff_sell_amt = 0, 0.0
    for o in orders:
        # 撤单类 (51/52/53/54) 不参与计算
        if o.status in ('51', '52', '53', '54'):
            continue
        vol = int(o.volume or 0)
        traded = int(o.traded_volume or 0)
        if traded > 0:
            unfilled = vol - traded
        else:
            # 委托还没成交: 全按未成交市价配平
            unfilled = vol
            traded = 0
        price = float(o.price or 0)
        if o.order_type == "23":  # 买
            eff_buy_amt += price * traded
            eff_buy_vol += traded
            if unfilled > 0:
                fill_price = ask1 if ask1 > 0 else price
                eff_buy_amt += fill_price * unfilled
                eff_buy_vol += unfilled
        elif o.order_type == "24":  # 卖
            eff_sell_amt += price * traded
            eff_sell_vol += traded
            if unfilled > 0:
                fill_price = bid1 if bid1 > 0 else price
                eff_sell_amt += fill_price * unfilled
                eff_sell_vol += unfilled

    # v62: 配平后算 realized
    paired_vol = min(eff_buy_vol, eff_sell_vol)
    total_realized = 0.0
    total_commission = 0.0
    total_stamp_tax = 0.0
    if paired_vol > 0:
        avg_buy = eff_buy_amt / eff_buy_vol if eff_buy_vol > 0 else 0.0
        avg_sell = eff_sell_amt / eff_sell_vol if eff_sell_vol > 0 else 0.0
        gross = (avg_sell - avg_buy) * paired_vol
        commission, stamp_tax = calc_commission_and_tax(avg_sell * paired_vol, fee_cfg, "SELL")
        total_realized = _q2(gross - commission - stamp_tax)
        total_commission = _q2(commission)
        total_stamp_tax = _q2(stamp_tax)

    # v62: 按日分组 (daily) — 保留旧逻辑做时间序列展示
    order_no_set = {o.order_no for o in orders if o.traded_volume and int(o.traded_volume) > 0}
    trades = []
    if order_no_set:
        trades = db.query(Trade).filter(
            Trade.order_no.in_(order_no_set),
        ).all()

    # 按日分组
    by_day: Dict[str, Dict] = {}
    sell_trades_by_day: Dict[str, List[Trade]] = {}
    buy_trades_by_day: Dict[str, List[Trade]] = {}
    for tr in trades:
        d = tr.trd_date
        if d not in by_day:
            by_day[d] = {
                'trd_date': d, 'buy_vol': 0, 'sell_vol': 0,
                'buy_amt': 0.0, 'sell_amt': 0.0, 'realized_pnl': 0.0,
                'commission': 0.0, 'stamp_tax': 0.0, 'trade_count': 0,
            }
            sell_trades_by_day[d] = []
            buy_trades_by_day[d] = []
        if tr.order_type == "23":
            by_day[d]['buy_vol'] += int(tr.volume or 0)
            by_day[d]['buy_amt'] += float(tr.price or 0) * int(tr.volume or 0)
            buy_trades_by_day[d].append(tr)
        elif tr.order_type == "24":
            by_day[d]['sell_vol'] += int(tr.volume or 0)
            by_day[d]['sell_amt'] += float(tr.price or 0) * int(tr.volume or 0)
            sell_trades_by_day[d].append(tr)
        by_day[d]['trade_count'] += 1

    # 算每日 realized_pnl (cost_basis = 当日买入均价, 仅用于 daily 时间序列展示)
    daily_list = []
    winning_days = 0
    for d in sorted(by_day.keys()):
        day = by_day[d]
        if day['sell_vol'] > 0 and buy_trades_by_day.get(d):
            buy_amt = day['buy_amt']
            buy_vol = day['buy_vol']
            cb = buy_amt / buy_vol if buy_vol > 0 else 0.0
        else:
            cb = 0.0
            pos = db.query(Position).filter_by(stock_code=t.stock_code).first()
            cb = float(pos.cost_price) if pos else 0.0

        if sell_trades_by_day.get(d):
            daily_realized, daily_commission, daily_stamp_tax = calc_realized_pnl(
                sell_trades_by_day[d], cb, fee_cfg
            )
        else:
            daily_realized, daily_commission, daily_stamp_tax = 0.0, 0.0, 0.0
        day['realized_pnl'] = daily_realized
        day['commission'] = daily_commission
        day['stamp_tax'] = daily_stamp_tax
        if daily_realized > 0:
            winning_days += 1
        daily_list.append(day)

    # cum_pnl (daily 时间序列)
    cum = 0.0
    for d in daily_list:
        cum += d['realized_pnl']
        d['cum_pnl'] = _q2(cum)

    # unrealized (v62 沿用旧逻辑: 净敞口 × 最新价差)
    task_net_volume = _calc_task_net_volume(db, task_id)
    pos = db.query(Position).filter_by(stock_code=t.stock_code).first()
    cost_basis = float(pos.cost_price) if pos else 0.0
    last_price = _last_price(db, t.stock_code, fallback=cost_basis)
    unrealized_pnl = (last_price - cost_basis) * task_net_volume

    # trade/order count
    trade_count = len(trades)
    order_count = len(orders)
    trading_days = len(daily_list)
    win_rate = _q4(winning_days / trading_days) if trading_days > 0 else 0.0

    return {
        'task': {
            'id': t.id,
            'stock_code': t.stock_code,
            'status': t.status,
            'base_volume': t.base_volume,
            'target_volume': t.target_volume,
            'created_trd_date': t.created_trd_date,
            'closed_at': t.closed_at.isoformat() if t.closed_at else None,
        },
        'summary': {
            'task_net_volume': task_net_volume,
            'position_vol': int(pos.vol) if pos else 0,
            'task_attributed_vol': task_net_volume,
            'realized_pnl': _q2(total_realized),
            'unrealized_pnl': _q2(unrealized_pnl),
            'commission_total': _q2(total_commission),
            'stamp_tax_total': _q2(total_stamp_tax),
            'trade_count': trade_count,
            'order_count': order_count,
            'first_trd_date': daily_list[0]['trd_date'] if daily_list else None,
            'last_trd_date': daily_list[-1]['trd_date'] if daily_list else None,
            'trading_days': trading_days,
            'winning_days': winning_days,
            'win_rate': win_rate,
        },
        'daily': daily_list,
        'by_stock': [{
            'stock_code': t.stock_code,
            'realized_pnl': _q2(total_realized),
            'unrealized_pnl': _q2(unrealized_pnl),
            'task_count': 1,
            'trading_days': trading_days,
        }],
    }


def list_overview(db: Session, user_id: int, is_admin: bool = False) -> Dict:
    """整体做T收益: 跨所有 task 聚合 summary."""
    q = db.query(T0Task)
    if not is_admin:
        q = q.filter(T0Task.user_id == user_id)

    active_tasks = q.filter(T0Task.status == 'active').all()
    closed_tasks = q.filter(T0Task.status == 'closed').all()

    total_realized = 0.0
    total_unrealized = 0.0
    total_commission = 0.0
    total_stamp_tax = 0.0
    win_rates = []
    total_trading_days = 0

    for t in active_tasks + closed_tasks:
        s = aggregate_task_stats(db, t.id)['summary']
        if t.status == 'closed':
            total_realized += s['realized_pnl']
            total_commission += s['commission_total']
            total_stamp_tax += s['stamp_tax_total']
            if s['trading_days'] > 0:
                win_rates.append(s['win_rate'])
            total_trading_days += s['trading_days']
        else:
            total_unrealized += s['unrealized_pnl']

    avg_win_rate = _q4(sum(win_rates) / len(win_rates)) if win_rates else 0.0

    return {
        'active_task_count': len(active_tasks),
        'closed_task_count': len(closed_tasks),
        'archived_task_count': q.filter(T0Task.status == 'archived').count(),
        'total_realized_pnl': _q2(total_realized),
        'total_unrealized_pnl': _q2(total_unrealized),
        'total_commission': _q2(total_commission),
        'total_stamp_tax': _q2(total_stamp_tax),
        'avg_win_rate': avg_win_rate,
        'total_trading_days': total_trading_days,
    }


def list_overview_by_stock(db: Session, user_id: int, is_admin: bool = False) -> List[Dict]:
    """单券做T收益: 按 stock_code 聚合."""
    q = db.query(T0Task)
    if not is_admin:
        q = q.filter(T0Task.user_id == user_id)

    tasks = q.filter(T0Task.status.in_(('active', 'closed'))).all()

    by_stock: Dict[str, Dict] = {}
    for t in tasks:
        if t.stock_code not in by_stock:
            by_stock[t.stock_code] = {
                'stock_code': t.stock_code,
                'realized_pnl': 0.0,
                'unrealized_pnl': 0.0,
                'net_volume': 0,
                'task_count': 0,
                'trading_days': 0,
            }
        s = aggregate_task_stats(db, t.id)['summary']
        by_stock[t.stock_code]['realized_pnl'] += s['realized_pnl']
        by_stock[t.stock_code]['unrealized_pnl'] += s['unrealized_pnl']
        by_stock[t.stock_code]['net_volume'] += s['task_net_volume']
        by_stock[t.stock_code]['task_count'] += 1
        by_stock[t.stock_code]['trading_days'] += s['trading_days']

    return [
        {**v, 'realized_pnl': _q2(v['realized_pnl']), 'unrealized_pnl': _q2(v['unrealized_pnl'])}
        for v in by_stock.values()
    ]


# ───────────────────── Helpers ─────────────────────

def _calc_task_net_volume(db: Session, task_id: int) -> int:
    """task 内 buy_vol - sell_vol (跨日累加)."""
    orders = db.query(Order).filter(Order.task_id == task_id).all()
    buy_vol = 0
    sell_vol = 0
    for o in orders:
        if o.order_type == "23":
            buy_vol += int(o.volume or 0)
        elif o.order_type == "24":
            sell_vol += int(o.volume or 0)
    return buy_vol - sell_vol


def _last_price(db: Session, stock_code: str, fallback: float = 0.0) -> float:
    """取最新价 (走 quote_snapshots 表; 无则 fallback)."""
    from server.models.orm import QuoteSnapshot
    snap = db.query(QuoteSnapshot).filter_by(stock_code=stock_code).order_by(QuoteSnapshot.ts.desc()).first()
    if snap and float(snap.last_price or 0) > 0:
        return float(snap.last_price)
    return fallback


def _balance_reason(task_net: int, pos_vol: int, target: int, action: str) -> str:
    if action == 'NONE':
        return f"已配平 (净敞口 {task_net}, 持仓 {pos_vol}, 目标 {target})"
    direction = "买" if action == 'BUY' else "卖"
    return f"需{direction} (净敞口 {task_net}, 持仓 {pos_vol}, 目标 {target})"


def _compute_summary(db: Session, task: T0Task) -> Dict:
    """task 摘要 (轻量, 用于列表)."""
    s = aggregate_task_stats(db, task.id)['summary']
    return {
        'task_net_volume': s['task_net_volume'],
        'position_vol': s['position_vol'],
        'realized_pnl': s['realized_pnl'],
        'unrealized_pnl': s['unrealized_pnl'],
        'trading_days': s['trading_days'],
        'win_rate': s['win_rate'],
    }


def _task_to_dict(t: T0Task) -> Dict:
    return {c.name: getattr(t, c.name) for c in t.__table__.columns}