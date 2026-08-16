"""Phase 5 — Free-tools funnel API.

Public (no auth) estimators that funnel users into the marketplace. The CCTV
calculator is the first; more vertical calculators can be added here.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.cctv_calculator import CCTVCalcInput, estimate_cctv
from app.services.solar_calculator import SolarCalcInput, estimate_solar
from app.services.quote_calculator import QuoteCalcInput, estimate_quote
from app.services.bom_calculator import BOMCalcInput, estimate_bom
from app.services.price_estimator import PriceEstimatorInput, estimate_service_price

router = APIRouter()


@router.post("/cctv-calculator", response_model=dict)
async def cctv_calculator(inp: CCTVCalcInput) -> dict:
    est = estimate_cctv(inp)
    return {**est.model_dump(), "cta": "/cctv/intake"}


@router.post("/solar-calculator", response_model=dict)
async def solar_calculator(inp: SolarCalcInput) -> dict:
    est = estimate_solar(inp)
    return {**est.model_dump(), "cta": "/contractors?profession=solar"}


@router.post("/quote-calculator", response_model=dict)
async def quote_calculator(inp: QuoteCalcInput) -> dict:
    est = estimate_quote(inp)
    return {**est.model_dump(), "cta": f"/contractors?profession={inp.trade.lower()}"}


@router.post("/bom-calculator", response_model=dict)
async def bom_calculator(inp: BOMCalcInput) -> dict:
    est = estimate_bom(inp)
    return {**est.model_dump(), "cta": f"/contractors?profession={inp.trade.lower()}"}


@router.post("/price-estimator", response_model=dict)
async def price_estimator(inp: PriceEstimatorInput) -> dict:
    est = estimate_service_price(inp)
    return {**est.model_dump(), "cta": f"/contractors?profession={inp.trade.lower()}"}
