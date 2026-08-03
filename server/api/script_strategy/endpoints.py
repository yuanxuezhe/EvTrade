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
from server.strategy import service as svc
from server.strategy.templates.default_script import DEFAULT_SCRIPT

log = logging.getLogger(__name__)


router = APIRouter()


# ─────────────── Pydantic schemas ───────────────


class ParamSpec(BaseModel):
    key: str
    type: str = Field("int", regex="^(int|float|choice)$")
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


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    params_schema: Optional[List[ParamSpec]] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ScriptOut(BaseModel):
    id: int
    user_id: int
    name: str
    code: str
    params_schema: List[Dict[str, Any]] = []
    description: str = ""
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskCreate(BaseModel):
    """创建任务: 仅存配置, 不立即执行"""
    script_id: int
    stock_code: str
    params: Dict[str, Any] = {}
    # 以下回测专属字段可预存, run 时可被覆盖
    backtest_start_date: Optional[str] = None
    backtest_end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[str] = None  # 历史行情字段白名单, 例 'open,close,high,low,volume'


class TaskRun(BaseModel):
    """触发任务执行: 选择 mode"""
    mode: str = Field("backtest", regex="^(backtest|live)$")
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
    script_id: int
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
    user: User = Depends(get_current_user),
):
    return svc.list_scripts(
        user.id, is_admin=(user.role == "admin"),
        name=name, status=status_filter,
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
def get_script_endpoint(script_id: int, user: User = Depends(get_current_user)):
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
        )
    except ValueError as e:
        # 验证错误 (重名 / 字段问题) → 400
        raise HTTPException(status_code=400, detail={"code": "CREATE_FAILED", "msg": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "INTERNAL", "msg": str(e)})
    return out


@router.put("/scripts/{script_id}", response_model=ScriptOut)
def update_script_endpoint(
    script_id: int, req: ScriptUpdate, user: User = Depends(get_current_user),
):
    patch = req.dict(exclude_unset=True)
    if "params_schema" in patch and patch["params_schema"] is not None:
        patch["params_schema"] = [p if isinstance(p, dict) else p.dict() for p in patch["params_schema"]]
    out = svc.update_script(script_id, user.id, user.role == "admin", patch)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "SCRIPT_NOT_FOUND"})
    return out


@router.delete("/scripts/{script_id}", status_code=204)
def delete_script_endpoint(script_id: int, user: User = Depends(get_current_user)):
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
    return out


@router.post("/tasks/{task_id}/run", response_model=TaskOut)
def run_task_endpoint(task_id: int, req: TaskRun, user: User = Depends(get_current_user)):
    """触发任务执行 (回测 or 实盘)

    立刻返回 (后台线程异步执行), 详情面板 5s 刷新看进度
    """
    log.info(
        "[run_task] user=%s task_id=%d mode=%s backtest=%s~%s period=%s fields=%s",
        user.username, task_id, req.mode,
        req.backtest_start_date, req.backtest_end_date, req.period, req.fields,
    )
    out = svc.run_task(
        task_id=task_id, user_id=user.id, is_admin=(user.role == "admin"),
        mode=req.mode,
        backtest_start_date=req.backtest_start_date,
        backtest_end_date=req.backtest_end_date,
        period=req.period,
        fields=req.fields,
    )
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    log.info("[run_task] task_id=%d 启动成功 (后台执行)", task_id)
    return out

@router.post("/tasks/{task_id}/stop")
def stop_task_endpoint(task_id: int, user: User = Depends(get_current_user)):
    ok = svc.stop_task(task_id, user.id, user.role == "admin")
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return {"ok": True, "task_id": task_id}


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
    """给前端 ScriptDev.vue 编辑器作为初始内容"""
    return {
        "code": DEFAULT_SCRIPT,
        "params_schema": [
            {"key": "fast", "type": "int", "min": 3, "max": 10, "step": 1, "default": 5},
            {"key": "slow", "type": "int", "min": 15, "max": 30, "step": 5, "default": 20},
            {"key": "qty", "type": "int", "min": 100, "max": 1000, "step": 100, "default": 100},
        ],
    }


__all__ = ["router"]