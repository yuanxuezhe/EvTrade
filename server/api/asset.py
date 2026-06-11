from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from rpc.client import qry_asset

router = APIRouter()


class AssetItem(BaseModel):
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float


class AssetRpcResponse(BaseModel):
    code: int
    msg: str
    list: List[AssetItem]


@router.get("", response_model=AssetRpcResponse)
async def get_account_asset():
    try:
        data = await qry_asset()
        return AssetRpcResponse(
            code=int(data.get("code", -1)),
            msg=str(data.get("msg", "")),
            list=[AssetItem(**item) for item in data.get("list", [])],
        )
    except Exception as e:
        print(f"qry_asset error: {e}")
        return AssetRpcResponse(code=-1, msg=str(e), list=[])
