from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    customer = "customer"
    contractor = "contractor"


class LocationMixin(BaseModel):
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state_or_province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class UserCreate(LocationMixin):
    email: EmailStr
    password: str
    role: UserRole
    full_name: str
    phone: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(LocationMixin):
    id: int
    email: str
    role: str
    full_name: str
    phone: Optional[str] = None
    profession: Optional[str] = None
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: int
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
    ai_tone_preference: Optional[str] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None


class ContractorProfileUpdate(BaseModel):
    profession: Optional[str] = None
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: Optional[int] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
    ai_tone_preference: Optional[str] = None


class UserProfileUpdate(LocationMixin):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    ai_tone_preference: Optional[str] = None
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: Optional[int] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
