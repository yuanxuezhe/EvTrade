"""
sysconfig/__init__.py — 统一配置 cache (v78)

启动时一次性从 sys_config 表加载到内存, 业务层从 cache 读
- user='0' 默认配置
- user='<username>' 用户专属覆盖

读策略: get(user, key, default) → 先查 user 行, 缺失回退 user='0' 默认
写策略: set(user, key, val) → 同步更新 cache + DB
"""
import logging
import threading
from typing import Any, Optional

from sqlalchemy.orm import Session

from server.db import SessionLocal
from server.models.orm import SysConfig

log = logging.getLogger(__name__)

_lock = threading.RLock()

# 全局默认配置 (v78 整合)
# user='0' 表示默认, 启动时会 upsert 到 sys_config 表
DEFAULT_CONFIGS: list[dict] = [
    {"cfg_key": "commission_rate", "cfg_val": "0.0001", "desc": "佣金费率 (万一)"},
    {"cfg_key": "stamp_tax_rate", "cfg_val": "0.001", "desc": "印花税率 (千一)"},
    {"cfg_key": "slippage", "cfg_val": "0.001", "desc": "滑点 (0.1%)"},
    {"cfg_key": "min_commission", "cfg_val": "5.0", "desc": "最低佣金 (元)"},
    {"cfg_key": "auto_reconcile", "cfg_val": "0", "desc": "自动对账开关 (0=人工/1=自动)"},
    {"cfg_key": "auto_use_broker_data", "cfg_val": "1", "desc": "自动对账时以柜台为准 (0=本地/1=柜台)"},
    {"cfg_key": "trdtime", "cfg_val": "093000-113000;130000-153000", "desc": "交易时段 (分号分隔多段 HHMMSS-HHMMSS)"},
    {"cfg_key": "must_change_password_required", "cfg_val": "1", "desc": "首次登录强制改密 (0=关/1=开; 关掉后 seed 用户 must_change_password=True 也不再拦截)"},
] # v_next: 新增首次登录强制改密开关

# user → {cfg_key → cfg_val}
_cache: dict[str, dict[str, str]] = {}
_loaded: bool = False


def _row_to_dict(row: SysConfig) -> dict:
    return {
        "user": row.user,
        "cfg_key": row.cfg_key,
        "cfg_val": row.cfg_val,
        "desc": row.desc,
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }


def _ensure_defaults(db: Session) -> None:
    """确保 user='0' 默认配置行存在 (v78 整合: 从 fee_config/reconcile_config 一次性导入)"""
    existing = {
        row.cfg_key for row in db.query(SysConfig).filter(SysConfig.user == "0").all()
    }
    for cfg in DEFAULT_CONFIGS:
        if cfg["cfg_key"] not in existing:
            row = SysConfig(user="0", **cfg)
            db.add(row)
            log.info("sysconfig: seed default cfg_key=%s", cfg["cfg_key"])
    db.commit()


def load_all(db: Optional[Session] = None) -> None:
    """启动时一次性加载全表到 cache"""
    global _loaded
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        _ensure_defaults(db)
        rows = db.query(SysConfig).all()
        with _lock:
            new_cache: dict[str, dict[str, str]] = {}
            for r in rows:
                new_cache.setdefault(r.user, {})[r.cfg_key] = r.cfg_val
            _cache.clear()
            _cache.update(new_cache)
            _loaded = True
        log.info("sysconfig: loaded %d rows (%d users)", len(rows), len(_cache))
    finally:
        if close_db:
            db.close()


def is_loaded() -> bool:
    return _loaded


def _coerce(val: str, default: Any) -> Any:
    """按 default 的类型把 str 转回来"""
    if val is None:
        return default
    if isinstance(default, bool):
        return val.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(val)
        except (ValueError, TypeError):
            return default
    if isinstance(default, float):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    return val


def get(key: str, default: Any = None, user: str = "0") -> Any:
    """读配置 — user 优先, 缺失回退 user='0' 默认

    类型自动按 default 的类型 coerce (int/float/bool/str)
    """
    with _lock:
        user_dict = _cache.get(user, {})
        if key in user_dict:
            return _coerce(user_dict[key], default)
        default_dict = _cache.get("0", {})
        if key in default_dict:
            return _coerce(default_dict[key], default)
    return default


def get_raw(key: str, user: str = "0") -> Optional[str]:
    """读原始 str 值 (不 coerce)"""
    with _lock:
        if key in _cache.get(user, {}):
            return _cache[user][key]
        return _cache.get("0", {}).get(key)


def set_value(user: str, key: str, val: str, desc: str = "", updated_by: Optional[str] = None) -> None:
    """写配置 — 同步更新 cache + DB"""
    db = SessionLocal()
    try:
        row = db.query(SysConfig).filter_by(user=user, cfg_key=key).first()
        if row:
            row.cfg_val = val
            if desc:
                row.desc = desc
            row.updated_by = updated_by
        else:
            row = SysConfig(
                user=user, cfg_key=key, cfg_val=val,
                desc=desc or "", updated_by=updated_by,
            )
            db.add(row)
        db.commit()
        with _lock:
            _cache.setdefault(user, {})[key] = val
        log.info("sysconfig: set user=%s key=%s", user, key)
    finally:
        db.close()


def delete_value(user: str, key: str) -> bool:
    """删除配置 — 同步删 cache + DB"""
    db = SessionLocal()
    try:
        row = db.query(SysConfig).filter_by(user=user, cfg_key=key).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        with _lock:
            if user in _cache and key in _cache[user]:
                del _cache[user][key]
        return True
    finally:
        db.close()


def list_all(user: Optional[str] = None) -> list[dict]:
    """列出配置 — user 不传则返回所有 (UI 用)

    列出格式: [{user, cfg_key, cfg_val, desc, has_override}, ...]
    user='0' 行带 has_override=True 表示有用户专属覆盖
    """
    with _lock:
        out = []
        users = [user] if user else list(_cache.keys())
        seen_keys: set[str] = set()
        for u in sorted(users):
            for k, v in sorted(_cache.get(u, {}).items()):
                has_override = bool(u == "0" and any(
                    k in _cache.get(other, {})
                    for other in _cache if other != "0"
                ))
                out.append({
                    "user": u,
                    "cfg_key": k,
                    "cfg_val": v,
                    "has_override": has_override if u == "0" else True,
                })
                seen_keys.add((u, k))
        # user 过滤时, 也补上 user='0' 默认 (用于前端展示可继承的默认)
        if user and user != "0":
            for k, v in sorted(_cache.get("0", {}).items()):
                if (user, k) in seen_keys:
                    continue
                out.append({
                    "user": "0",
                    "cfg_key": k,
                    "cfg_val": v,
                    "has_override": False,
                    "inherited": True,
                })
        return out