"""
strategy/schemas.py — strategy API Pydantic schemas（change strategy_trade task 9）

约定：
- 单 schema/实体（id 可选，in/out 复用），orm_mode=True 让 FastAPI 从 ORM 转 out
- JSON 字段（required_flags / exclude_flags / flags_active / action_payload）用 validator
  兼容 ORM 原始字符串（Text 存 JSON）和 list/dict 输入
- datetime 字段用 Optional[datetime]，FastAPI 的 jsonable_encoder 会自动转 ISO 字符串
"""
import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, validator


class _OrmConfig(BaseModel):
    class Config:
        orm_mode = True


def _parse_json_list(v):
    """兼容 str（ORM 原始）/ list（新输入）→ list"""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            parsed = json.loads(v) if v else []
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return list(v) if hasattr(v, "__iter__") else []


def _parse_json_dict(v):
    """兼容 str（ORM 原始）/ dict/new 输入 → dict 或 None"""
    if v is None or v == "" or v == "null":
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None
    return v


class GridSchema(_OrmConfig):
    id: Optional[int] = None
    direction: str
    step_offset: float = 0.0
    trigger_price: float = 0.0
    volume: int = 0
    max_fires: Optional[int] = None
    fired_count: int = 0
    enabled: bool = True
    priority: int = 0


class RegimeSchema(_OrmConfig):
    id: Optional[int] = None
    name: str
    priority: int = 0
    required_flags: List[str] = []
    exclude_flags: List[str] = []
    base_volume: Optional[int] = None
    clear_position: bool = False
    enabled: bool = True
    grids: List[GridSchema] = []

    @validator("required_flags", "exclude_flags", pre=True)
    def _parse_flags(cls, v):
        return _parse_json_list(v)


class StrategyOut(_OrmConfig):
    id: int
    user_id: int
    stock_code: str
    type: str
    reference_price: float
    status: str
    base_volume: int
    note: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    regimes: List[RegimeSchema] = []


class StrategyCreate(BaseModel):
    stock_code: str
    type: str = "general"
    reference_price: float = 0.0
    base_volume: int = 0
    note: str = ""
    regimes: List[RegimeSchema] = []


class StrategyUpdate(BaseModel):
    status: Optional[str] = None
    type: Optional[str] = None
    reference_price: Optional[float] = None
    base_volume: Optional[int] = None
    note: Optional[str] = None


class ControlRequest(BaseModel):
    action: str  # pause / resume / stop / clear_now


class AuditRecord(_OrmConfig):
    id: int
    strategy_id: int
    regime_id: Optional[int] = None
    trd_date: str
    trigger_type: str
    flags_active: List[str] = []
    current_price: Optional[float] = None
    position_vol: Optional[int] = None
    base_volume: Optional[int] = None
    action_payload: Optional[dict] = None
    order_no: Optional[str] = None
    reject_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    @validator("flags_active", pre=True)
    def _parse_flags(cls, v):
        return _parse_json_list(v)

    @validator("action_payload", pre=True)
    def _parse_payload(cls, v):
        return _parse_json_dict(v)


class FlagDefinition(BaseModel):
    code: str
    name: str
    category: str
    description: str


class FlagDefinitionsResponse(BaseModel):
    list: List[FlagDefinition]
