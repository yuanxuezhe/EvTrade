"""
server/api/script_strategy/scripts.py — 脚本库端点 (v123)

REST 端点 (前缀 /api/script-strategy):
  GET    /scripts                list (含分页)
  GET    /scripts/by-name/{name} 按名查
  GET    /scripts/{id}           detail
  POST   /scripts                create
  PUT    /scripts/{id}           update
  DELETE /scripts/{id}           delete
  GET    /templates/default      默认脚本模板 (供前端编辑器初始化)

任务端点见 tasks.py; 策略/回测/实盘见 strategies.py。
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from server.auth.deps import get_current_user
from server.models.user import User
from server.services import script_strategy as svc
from server.api.script_strategy.schemas import ScriptCreate, ScriptOut, ScriptUpdate

log = logging.getLogger(__name__)

router = APIRouter()


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


@router.get("/templates/default")
def get_default_script_template():
    """给前端 ScriptDev.vue 编辑器作为初始内容

    v120+ strategy-exec-service: 模板迁到 strategy_exec/templates/default_bt_strategy.py
    读 strategy_exec 的默认 demo (避免重复实现, 单一事实源)
    """
    import ast
    import os
    # strategy_exec/templates/default_bt_strategy.py 在 EvTrade 项目根下
    _TEMPLATE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "strategy_exec", "strategy_exec", "templates", "default_bt_strategy.py",
    )
    code_str = "# DEFAULT_BT_STRATEGY_CODE not found"
    params_schema: list = []
    try:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        # 提取 DEFAULT_BT_STRATEGY_CODE / DEFAULT_BT_STRATEGY_PARAMS_SCHEMA
        # schema 与代码同源解析 → 避免硬编码漂移导致 strict mode 不一致
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "DEFAULT_BT_STRATEGY_CODE":
                    code_str = ast.literal_eval(node.value)
                elif target.id == "DEFAULT_BT_STRATEGY_PARAMS_SCHEMA":
                    params_schema = ast.literal_eval(node.value)
    except Exception as e:
        log.warning("[template] 读 strategy_exec 模板失败: %s", e)
        code_str = f"# 模板加载失败: {e}\n# 请检查 strategy_exec/templates/default_bt_strategy.py"
    if not params_schema:
        # 兜底: 与模板 DEFAULT_BT_STRATEGY_PARAMS_SCHEMA 保持一致 (含 rsi_period)
        params_schema = [
            {"key": "fast", "type": "int", "min": 3, "max": 30, "step": 1, "default": 5},
            {"key": "slow", "type": "int", "min": 10, "max": 120, "step": 1, "default": 20},
            {"key": "qty", "type": "int", "min": 100, "max": 10000, "step": 100, "default": 100},
            {"key": "rsi_period", "type": "int", "min": 6, "max": 30, "step": 1, "default": 14},
        ]
    return {"code": code_str, "params_schema": params_schema}


__all__ = ["router"]
