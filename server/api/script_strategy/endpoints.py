"""
server/api/script_strategy/__init__.py + endpoints.py

REST 端点:
  GET    /api/script-strategy/scripts                list (含分页)
  GET    /api/script-strategy/scripts/{id}           detail
  POST   /api/script-strategy/scripts                create
  PUT    /api/script-strategy/scripts/{id}           update
  DELETE /api/script-strategy/scripts/{id}           delete

  GET    /api/script-strategy/tasks                  list
  GET    /api/script-strategy/tasks/{id}             detail
  POST   /api/script-strategy/tasks                  create + 启动
  POST   /api/script-strategy/tasks/{id}/stop        stop
  DELETE /api/script-strategy/tasks/{id}             delete
  GET    /api/script-strategy/tasks/{id}/logs        运行日志

  GET    /api/script-strategy/templates/default      默认脚本模板 (供前端编辑器初始化)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

from server.auth.deps import get_current_user
from server.models.user import User
# v120+ strategy-exec-service: 策略运行迁到独立服务
# Script CRUD (scripts/tasks POST/PUT/DELETE/GET) 仍用 service (直接读写 strategy_script/task 表)
# 2026-08-09: 旧 server/strategy/service.py 已删, CRUD 迁到 server/services/script_strategy
from server.services import script_strategy as svc
# DEFAULT_SCRIPT 模板迁到 strategy_exec/templates/default_bt_strategy.py

from server.services.script_strategy._convert import json_loads
log = logging.getLogger(__name__)


router = APIRouter()


# ─────────────── Pydantic schemas ───────────────


class ParamSpec(BaseModel):
    key: str
    type: str = Field("int", pattern="^(int|float|choice)$")
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    default: Any = None
    values: Optional[List[Any]] = None


class ScriptCreate(BaseModel):
    name: str
    code: str
    params_schema: List[ParamSpec] = []
    description: str = ""
    is_public: bool = False  # v90+ 是否公开 (其他用户可见)


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    params_schema: Optional[List[ParamSpec]] = None
    description: Optional[str] = None
    status: Optional[str] = None
    is_public: Optional[bool] = None  # v90+ 可改公开状态


class ScriptOut(BaseModel):
    id: str  # v90+ 复合 PK: (user_id, id), id 字符串 (用户自命名)
    user_id: int
    name: str
    code: str
    params_schema: List[Dict[str, Any]] = []
    description: str = ""
    status: str
    is_public: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskCreate(BaseModel):
    """创建任务: 仅存配置, 不立即执行"""
    script_id: str  # v90+ 改 varchar
    stock_code: str
    params: Dict[str, Any] = {}
    # 以下回测专属字段可预存, run 时可被覆盖
    backtest_start_date: Optional[str] = None
    backtest_end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[str] = None  # 历史行情字段白名单, 例 'open,close,high,low,volume'


class TaskRun(BaseModel):
    """触发任务执行: 选择 mode"""
    mode: str = Field("backtest", pattern="^(backtest|live)$")
    # 可选: run 时覆盖 task 创建时的 params (便于试不同参数)
    params: Optional[Dict[str, Any]] = None
    # 回测专属
    backtest_start_date: Optional[str] = None
    backtest_end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    user_id: int
    script_id: str  # v90+ 改 varchar
    stock_code: str
    mode: Optional[str] = None
    status: str
    params: Dict[str, Any] = {}
    backtest_result: Optional[Dict[str, Any]] = None
    best_params: Optional[Dict[str, Any]] = None
    backtest_start_date: Optional[str] = None
    backtest_end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[str] = None
    pnl: float = 0.0
    positions: Optional[Dict[str, Any]] = None
    trades_count: int = 0
    live_signals: List[Dict[str, Any]] = []
    progress: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─────────────── Script endpoints ───────────────


@router.get("/scripts", response_model=List[ScriptOut])
def list_scripts_endpoint(
    name: Optional[str] = Query(None, description="模糊搜索 name"),
    status_filter: Optional[str] = Query(None, alias="status", description="active/archived"),
    only_mine: bool = Query(False, description="仅列自己的 (默认包含公开脚本)"),
    user: User = Depends(get_current_user),
):
    return svc.list_scripts(
        user.id, is_admin=(user.role == "admin"),
        name=name, status=status_filter, only_mine=only_mine,
    )


@router.get("/scripts/by-name/{name}", response_model=ScriptOut)
def get_script_by_name_endpoint(name: str, user: User = Depends(get_current_user)):
    """按 name 查脚本 (前端的 '脚本选择' 下拉用)

    例: /scripts/by-name/ma5_e2e → 返 id=4 的脚本
    """
    out = svc.get_script_by_name(name, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "SCRIPT_NOT_FOUND", "name": name})
    return out


@router.get("/scripts/{script_id}", response_model=ScriptOut)
def get_script_endpoint(script_id: str, user: User = Depends(get_current_user)):
    out = svc.get_script(script_id, user.id, is_admin=(user.role == "admin"))
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "SCRIPT_NOT_FOUND"})
    return out


@router.post("/scripts", response_model=ScriptOut, status_code=201)
def create_script_endpoint(req: ScriptCreate, user: User = Depends(get_current_user)):
    try:
        out = svc.create_script(
            user_id=user.id, name=req.name, code=req.code,
            params_schema=[p.dict() for p in req.params_schema],
            description=req.description,
            is_public=req.is_public,
        )
    except ValueError as e:
        # 验证错误 (重名 / 字段问题) → 400
        raise HTTPException(status_code=400, detail={"code": "CREATE_FAILED", "msg": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})
    return out


@router.put("/scripts/{script_id}", response_model=ScriptOut)
def update_script_endpoint(
    script_id: str, req: ScriptUpdate, user: User = Depends(get_current_user),
):
    patch = req.dict(exclude_unset=True)
    if "params_schema" in patch and patch["params_schema"] is not None:
        patch["params_schema"] = [p if isinstance(p, dict) else p.dict() for p in patch["params_schema"]]
    out = svc.update_script(script_id, user.id, user.role == "admin", patch)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "SCRIPT_NOT_FOUND"})
    return out


@router.delete("/scripts/{script_id}", status_code=204)
def delete_script_endpoint(script_id: str, user: User = Depends(get_current_user)):
    ok = svc.delete_script(script_id, user.id, user.role == "admin")
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "SCRIPT_NOT_FOUND"})
    return None


# ─────────────── Task endpoints ───────────────


@router.get("/tasks", response_model=List[TaskOut])
def list_tasks_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    mode_filter: Optional[str] = Query(None, alias="mode"),
    user: User = Depends(get_current_user),
):
    return svc.list_tasks(user.id, user.role == "admin", status=status_filter, mode=mode_filter)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    out = svc.get_task(task_id, user.id, user.role == "admin")
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task_endpoint(req: TaskCreate, user: User = Depends(get_current_user)):
    """创建任务 (不立即执行, status='created'), 需再调 /tasks/{id}/run 触发"""
    try:
        out = svc.create_task(
            user_id=user.id, script_id=req.script_id, stock_code=req.stock_code,
            params=req.params,
            backtest_start_date=req.backtest_start_date,
            backtest_end_date=req.backtest_end_date,
            period=req.period,
            fields=req.fields,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "CREATE_FAILED", "msg": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})
    return out


@router.post("/tasks/{task_id}/run", response_model=TaskOut)
async def run_task_endpoint(task_id: int, req: TaskRun, user: User = Depends(get_current_user)):
    """触发任务执行 (回测 or 实盘)

    v120+ (change strategy-exec-service): 转发到独立 strategy_exec 服务 (8001)
    不再本地启动 Backtrader — 引擎迁移到 strategy_exec/

    立刻返回 202 (后台异步执行), 详情面板 5s 刷新看进度
    """
    log.info(
        "[run_task] user=%s task_id=%d mode=%s backtest=%s~%s period=%s fields=%s",
        user.username, task_id, req.mode,
        req.backtest_start_date, req.backtest_end_date, req.period, req.fields,
    )

    # ──── 1. 权限校验 + 读 task ────
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
    if row.status in ("running", "live"):
        raise HTTPException(
            status_code=409,
            detail={"code": "ALREADY_RUNNING", "msg": f"任务已在 {row.status}"},
        )

    # ──── 2. 参数校验：回测必须指定起止日期 ────
    if req.mode == "backtest":
        if not req.backtest_start_date:
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_PARAM", "msg": "回测模式必须指定 backtest_start_date（格式 YYYYMMDD）"},
            )
        if not req.backtest_end_date:
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_PARAM", "msg": "回测模式必须指定 backtest_end_date（格式 YYYYMMDD）"},
            )

    # ──── 3. 预写 status='queued' + mode + execution_service='strategy_exec' ────
    from datetime import datetime
    from server.config import settings
    task_data = row._data
    task_data["status"] = "queued"
    task_data["mode"] = req.mode
    task_data["execution_service"] = "strategy_exec"
    task_data["started_at"] = datetime.now()
    task_data["finished_at"] = None
    task_data["error_msg"] = None
    row.update()

    # ──── 3. 转发到 strategy_exec ────
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/run-task",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json={
                    "task_id": task_id,
                    "user_id": row.user_id,
                    "script_id": row.script_id,
                    "stock_code": row.stock_code,
                    "mode": req.mode,
                    "params": json_loads(task_data.get("params")) or {},
                    "backtest_start_date": req.backtest_start_date,
                    "backtest_end_date": req.backtest_end_date,
                    "period": req.period,
                    "fields": req.fields,
                },
            )
    except httpx.TimeoutException as e:
        err_msg = f"strategy_exec 请求超时（60s）: {e}"
        log.error("[run_task] %s", err_msg)
        task_data["status"] = "created"
        task_data["error_msg"] = err_msg
        row.update()
        raise HTTPException(
            status_code=503,
            detail={"code": "STRATEGY_EXEC_TIMEOUT", "msg": err_msg},
        )
    except httpx.RequestError as e:
        err_msg = f"strategy_exec 连接失败: {type(e).__name__} {e}"
        log.error("[run_task] %s", err_msg)
        task_data["status"] = "created"
        task_data["error_msg"] = err_msg
        row.update()
        raise HTTPException(
            status_code=503,
            detail={"code": "STRATEGY_EXEC_UNAVAILABLE", "msg": err_msg},
        )

    if response.status_code >= 400:
        err_body = response.text
        log.error("[run_task] strategy_exec returned %d: %s",
                  response.status_code, err_body)
        # 把 strategy_exec 的详细错误透传给前端
        task_data["status"] = "created"
        task_data["error_msg"] = err_body
        row.update()
        try:
            err_json = response.json()
            err_msg = err_json.get("detail", {}).get("msg", err_body) if isinstance(err_json.get("detail"), dict) else str(err_json.get("detail", err_body))
        except Exception:
            err_msg = err_body
        raise HTTPException(
            status_code=response.status_code,
            detail={"code": err_json.get("detail", {}).get("code", "STRATEGY_EXEC_ERROR") if isinstance(err_json.get("detail"), dict) else "STRATEGY_EXEC_ERROR",
                    "msg": err_msg},
        )

    log.info("[run_task] task_id=%d forwarded to strategy_exec OK", task_id)
    # 返 task 详情 (status='queued', 等 strategy_exec 异步改 running)
    from server.services import script_strategy as svc
    return svc.get_task(task_id, row.user_id, is_admin=True)


@router.post("/tasks/{task_id}/stop")
async def stop_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    """停止任务 (v120+: 转发到 strategy_exec)"""
    from server.tables import StrategyTask
    from server.config import settings
    import httpx

    row = StrategyTask.query_one(id=task_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.STRATEGY_EXEC_API_URL}/internal/stop-task",
                headers={"X-Internal-Token": settings.STRATEGY_EXEC_API_TOKEN},
                json={"task_id": task_id},
            )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
        if response.status_code >= 400:
            log.warning("[stop_task] strategy_exec returned %d: %s",
                        response.status_code, response.text)
        return {"ok": True, "task_id": task_id}
    except httpx.RequestError as e:
        log.exception("[stop_task] forward failed")
        # 兜底: 直接标 stopped (即使 strategy_exec 不可达, task 状态也能在本地改)
        from datetime import datetime
        task_data = row._data
        task_data["status"] = "stopped"
        task_data["finished_at"] = datetime.now()
        row.update()
        return {"ok": True, "task_id": task_id, "fallback": True}


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    ok = svc.delete_task(task_id, user.id, user.role == "admin")
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return None


@router.get("/tasks/{task_id}/logs")
def get_task_logs_endpoint(task_id: int, user: User = Depends(get_current_user)):
    out = svc.get_task_logs(task_id, user.id, user.role == "admin")
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.get("/tasks/{task_id}/signals")
def get_task_signals_endpoint(
    task_id: int,
    type_filter: Optional[str] = Query(None, alias="type", description="BUY/SELL/INFO/WARN"),
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """返任务的信号流 + 进度时间轴

    回测模式: 从 backtest_result.signal_log 返
    实盘模式: 从 strategy_task.live_signals 返 (LiveRunner 每 5s flush)
    """
    out = svc.get_task_signals(task_id, user.id, user.role == "admin",
                                type_filter=type_filter, limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


@router.get("/tasks/{task_id}/audit")
def get_task_audit_endpoint(
    task_id: int,
    trigger_type: Optional[str] = Query(None, description="BUY/SELL/INFO/..."),
    trd_date: Optional[str] = Query(None, description="YYYYMMDD"),
    limit: int = Query(500, ge=1, le=5000),
    user: User = Depends(get_current_user),
):
    """返 task 永久 audit (从 strategy_script_audit 表)

    📌 与 /signals 区别:
    - /signals: 限 500 条, 实时 in-memory
    - /audit:  永久存 DB, 支持按 trd_date / trigger_type 过滤, 量级无上限
    """
    out = svc.get_task_audit(task_id, user.id, user.role == "admin",
                              trigger_type=trigger_type, trd_date=trd_date, limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


# ─────────────── Template ───────────────


@router.get("/templates/default")
def get_default_script_template():
    """给前端 ScriptDev.vue 编辑器作为初始内容

    v120+ strategy-exec-service: 模板迁到 strategy_exec/templates/default_bt_strategy.py
    读 strategy_exec 的默认 demo (避免重复实现, 单一事实源)
    """
    import os
    # strategy_exec/templates/default_bt_strategy.py 在 EvTrade 项目根下
    _TEMPLATE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "strategy_exec", "strategy_exec", "templates", "default_bt_strategy.py",
    )
    try:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        # 提取 DEFAULT_BT_STRATEGY_CODE 字符串内容
        import ast
        tree = ast.parse(src)
        code_str = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DEFAULT_BT_STRATEGY_CODE":
                        code_str = ast.literal_eval(node.value)
                        break
        if code_str is None:
            code_str = "# DEFAULT_BT_STRATEGY_CODE not found"
    except Exception as e:
        log.warning("[template] 读 strategy_exec 模板失败: %s", e)
        code_str = f"# 模板加载失败: {e}\n# 请检查 strategy_exec/templates/default_bt_strategy.py"

    return {
        "code": code_str,
        "params_schema": [
            {"key": "fast", "type": "int", "min": 3, "max": 10, "step": 1, "default": 5},
            {"key": "slow", "type": "int", "min": 15, "max": 30, "step": 5, "default": 20},
            {"key": "qty", "type": "int", "min": 100, "max": 1000, "step": 100, "default": 100},
        ],
    }


__all__ = ["router"]