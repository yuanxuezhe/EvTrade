"""
server/api/script_strategy/endpoints.py — scripts + tasks 端点 (v123)

REST 端点:
  GET    /api/script-strategy/scripts                list (含分页)
  GET    /api/script-strategy/scripts/by-name/{name} 按名查
  GET    /api/script-strategy/scripts/{id}           detail
  POST   /api/script-strategy/scripts                create
  PUT    /api/script-strategy/scripts/{id}           update
  DELETE /api/script-strategy/scripts/{id}           delete

  GET    /api/script-strategy/tasks                  list (可按 strategy_id 过滤)
  GET    /api/script-strategy/tasks/{id}             detail
  POST   /api/script-strategy/tasks/{id}/stop        stop
  DELETE /api/script-strategy/tasks/{id}             delete
  GET    /api/script-strategy/tasks/{id}/logs        running logs
  GET    /api/script-strategy/tasks/{id}/signals     信号流 + 进度时间轴
  GET    /api/script-strategy/tasks/{id}/audit       永久 audit

  GET    /api/script-strategy/templates/default      默认脚本模板 (供前端编辑器初始化)

策略/回测/实盘端点见 strategies.py:
  /strategies ... /strategies/{id}/backtest /batches /live (v123)
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server.auth.deps import get_current_user
from server.models.user import User
# v120+ strategy-exec-service: 策略运行迁到独立服务
# Script/Task CRUD (GET/POST/PUT/DELETE) 仍用 service (直接读写 strategy_script/task 表)
# 2026-08-09: 旧 server/strategy/service.py 已删, CRUD 迁到 server/services/script_strategy
from server.services import script_strategy as svc
# DEFAULT_SCRIPT 模板迁到 strategy_exec/templates/default_bt_strategy.py

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


class TaskOut(BaseModel):
    id: int
    user_id: int
    strategy_id: Optional[int] = None  # v123: 挂策略不挂脚本
    batch_no: Optional[int] = None     # v123: 批次号 (序号表 task_batch)
    description: str = ""
    stock_code: str
    mode: Optional[str] = None
    status: str
    params: Dict[str, Any] = {}
    backtest_result: Optional[Dict[str, Any]] = None
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
    backtest_metric_value: Optional[float] = None


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

# v123: 任务创建统一走 /strategies/{id}/backtest (single/sweep) 与 /strategies/{id}/live,
# 不再有 POST /tasks 与 /tasks/{id}/run(/run-sweep)。


@router.get("/tasks", response_model=List[TaskOut])
def list_tasks_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    mode_filter: Optional[str] = Query(None, alias="mode"),
    strategy_id: Optional[int] = Query(None, description="v123: 限定策略 ID"),
    limit: int = Query(50, ge=1, le=200, description="最大返回数 (默认 50, 上限 200)"),
    user: User = Depends(get_current_user),
):
    """列 task

    v123 filter:
    - strategy_id: 限定策略
    - limit: 默认 50, 上限 200
    """
    return svc.list_tasks(
        user.id, user.role == "admin",
        status=status_filter, mode=mode_filter,
        strategy_id=strategy_id,
        limit=limit,
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    out = svc.get_task(task_id, user.id, user.role == "admin")
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return out


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
