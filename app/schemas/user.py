from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    customer = "customer"
    contractor = "contractor"
    admin = "admin"


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: UserRole
    full_name: str
    phone: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state_or_province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    full_name: str
    phone: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state_or_province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    profession: Optional[str] = None
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: int
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
    ai_tone_preference: Optional[str] = None
    ai_autonomy_level: int = 1
    verification_level: Optional[str] = None
    reputation_score: Optional[float] = None
    availability_status: Optional[str] = None

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
    ai_autonomy_level: int = 1
    verification_level: Optional[str] = None
    reputation_score: Optional[float] = None
    availability_status: Optional[str] = None


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state_or_province: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    profession: Optional[str] = None
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: Optional[int] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
    ai_tone_preference: Optional[str] = None
    ai_autonomy_level: int = 1
    verification_level: Optional[str] = None
    reputation_score: Optional[float] = None
    availability_status: Optional[str] = None

    class Config:
        from_attributes = True