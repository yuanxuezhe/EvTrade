from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import traceback
from rpc.client import qry_asset

router = APIRouter()

class AssetResponse(BaseModel):
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float

@router.get("", response_model=AssetResponse)
async def get_account_asset():
    try:
        data = await qry_asset()
        return AssetResponse(
            cash=data.get("cash", 0),
            frozen_cash=data.get("frozen_cash", 0),
            market_value=data.get("market_value", 0),
            total_asset=data.get("total_asset", 0)
        )
    except Exception as e:
        print(f"qry_asset error: {e}")
        return AssetResponse(cash=0, frozen_cash=0, market_value=0, total_asset=0)