"""
server/api/script_strategy/schemas/scripts.py — Script 端点 Pydantic 模型

职责单一: 脚本 (Script) 的请求与响应 schema, 无业务逻辑。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────── Script ───────────────


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
    is_public: bool = False  # 是否公开 (其他用户可见)


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    params_schema: Optional[List[ParamSpec]] = None
    description: Optional[str] = None
    status: Optional[str] = None
    is_public: Optional[bool] = None  # 可改公开状态


class ScriptOut(BaseModel):
    id: str  # 复合 PK: (user_id, id), id 字符串 (用户自命名)
    user_id: int
    name: str
    code: str
    params_schema: List[Dict[str, Any]] = []
    description: str = ""
    status: str
    is_public: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
