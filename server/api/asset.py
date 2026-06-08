from fastapi import APIRouter
from pydantic import BaseModel
from services.trading import get_asset

router = APIRouter()

class AssetResponse(BaseModel):
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float

@router.get("", response_model=AssetResponse)
async def get_account_asset():
    asset = get_asset()
    return AssetResponse(
        cash=asset.cash,
        frozen_cash=asset.frozen_cash,
        market_value=asset.market_value,
        total_asset=asset.total_asset
    )