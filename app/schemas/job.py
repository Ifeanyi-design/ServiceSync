from pydantic import BaseModel
from typing import List, Optional


class JobLocationMixin:
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state_or_province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class JobCreate(BaseModel, JobLocationMixin):
    description: str
    urgency: Optional[str] = None # low, medium, high, emergency
    extracted_skills: List[str] = []


class JobResponse(BaseModel, JobLocationMixin):
    id: int
    customer_id: int
    assigned_contractor_id: Optional[int]
    description: str
    status: str
    urgency: Optional[str] = None
    is_emergency: bool = False

    class Config:
        from_attributes = True


class BookJobRequest(BaseModel):
    contractor_id: int
