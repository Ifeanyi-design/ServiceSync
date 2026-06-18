from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Dict, Any
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2

from app.models.all_models import User, Job


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_same_text(user_value: Any, contractor_value: Any) -> bool:
    return bool(_clean(user_value) and _clean(user_value) == _clean(contractor_value))


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * radius_miles * atan2(sqrt(a), sqrt(1 - a))


def calculate_distance(user_location: Dict[str, Any], contractor: User) -> float:
    user_lat = user_location.get("latitude")
    user_lon = user_location.get("longitude")
    contractor_lat = contractor.latitude
    contractor_lon = contractor.longitude

    if all(isinstance(value, (int, float)) for value in [user_lat, user_lon, contractor_lat, contractor_lon]):
        return round(_haversine_miles(float(user_lat), float(user_lon), float(contractor_lat), float(contractor_lon)), 1)

    if _has_same_text(user_location.get("city"), contractor.city):
        return 5.0
    if _has_same_text(user_location.get("state_or_province"), contractor.state_or_province):
        return 15.0
    if _has_same_text(user_location.get("country"), contractor.country):
        return 50.0

    user_zip = _clean(user_location.get("zip_code") or user_location.get("postal_code"))
    contractor_zip = _clean(contractor.zip_code or contractor.postal_code)
    if user_zip and contractor_zip and user_zip[:2] == contractor_zip[:2]:
        return 5.0
    if user_zip and contractor_zip:
        return 25.0

    return 999.0


def _location_is_usable(user_location: Dict[str, Any]) -> bool:
    return any([
        user_location.get("latitude") is not None and user_location.get("longitude") is not None,
        user_location.get("city"),
        user_location.get("area"),
        user_location.get("state_or_province"),
        user_location.get("country"),
        user_location.get("zip_code"),
        user_location.get("postal_code"),
    ])


async def find_matches(db: AsyncSession, profession: str, location: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Finds contractors matching trade and global location.

    Backward-compatible: callers may still pass {"zip_code": "90210"}.
    Phase 1 preferred input: {"country": "NG", "city": "Lagos", "area": "Ikeja"}.
    """
    location = location or {}
    if not _location_is_usable(location):
        return {"matched": [], "rejected": [{"reason": "Location is required for matching"}]}

    profession_clean = _clean(profession)
    query = select(User).where(User.role == "contractor")
    result = await db.exec(query)
    contractors = result.all()

    matched = []
    rejected = []
    today = datetime.now(timezone.utc).date()

    for contractor in contractors:
        if profession_clean and not _has_same_text(profession_clean, contractor.profession):
            continue

        jobs_query = select(Job).where(Job.assigned_contractor_id == contractor.id)
        jobs_result = await db.exec(jobs_query)
        jobs_today = sum(1 for job in jobs_result.all() if job.created_at.date() == today)

        if jobs_today >= contractor.max_daily_jobs:
            rejected.append({
                "contractor_id": contractor.id,
                "reason": f"Daily limit reached ({jobs_today}/{contractor.max_daily_jobs})"
            })
            continue

        distance = calculate_distance(location, contractor)
        if contractor.service_radius_miles is not None and distance > contractor.service_radius_miles:
            rejected.append({
                "contractor_id": contractor.id,
                "reason": f"Outside service radius ({distance} > {contractor.service_radius_miles})"
            })
            continue

        matched.append({
            "contractor_id": contractor.id,
            "full_name": contractor.full_name,
            "profession": contractor.profession,
            "base_pricing": contractor.base_pricing,
            "distance": distance,
            "city": contractor.city,
            "area": contractor.area,
            "country": contractor.country,
            "postal_code": contractor.postal_code or contractor.zip_code,
        })

    return {
        "matched": matched,
        "rejected": rejected
    }
