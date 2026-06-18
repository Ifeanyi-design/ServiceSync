from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, JSON
from datetime import datetime

class OmnichannelIntegration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contractor_id: int = Field(foreign_key="user.id")
    platform: str # "whatsapp", "telegram", "messenger"
    platform_account_id: str
    access_token: str
    is_active: bool = Field(default=True)
    
    contractor: "User" = Relationship(back_populates="integrations")

class DirectMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    sender_id: int = Field(foreign_key="user.id")
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    conversation: "Conversation" = Relationship(back_populates="messages")

class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    customer_id: int = Field(foreign_key="user.id")
    contractor_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    messages: List[DirectMessage] = Relationship(back_populates="conversation")

class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id")
    assigned_contractor_id: Optional[int] = Field(default=None, foreign_key="user.id")
    description: str
    status: str = Field(default="open") # open, matched, booked, completed, cancelled
    urgency: Optional[str] = Field(default=None) # low, medium, high, emergency
    is_emergency: bool = Field(default=False)
    country: Optional[str] = Field(default=None)
    state_or_province: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    area: Optional[str] = Field(default=None)
    postal_code: Optional[str] = Field(default=None)
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    customer: "User" = Relationship(back_populates="jobs", sa_relationship_kwargs={"foreign_keys": "[Job.customer_id]"})
    assigned_contractor: Optional["User"] = Relationship(back_populates="assigned_jobs", sa_relationship_kwargs={"foreign_keys": "[Job.assigned_contractor_id]"})

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str # "customer", "contractor"
    full_name: str
    phone: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = Field(default=None)
    state_or_province: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    area: Optional[str] = Field(default=None)
    postal_code: Optional[str] = Field(default=None)
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    
    # Contractor specific configurations
    profession: Optional[str] = None # e.g., "plumber"
    service_radius_miles: Optional[int] = None
    base_pricing: Optional[float] = None
    max_daily_jobs: int = Field(default=4)               
    working_hours_start: Optional[str] = Field(default="08:00") 
    working_hours_end: Optional[str] = Field(default="18:00")   
    ai_tone_preference: Optional[str] = Field(default="professional")
    trade_qualifications: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    jobs: List[Job] = Relationship(back_populates="customer", sa_relationship_kwargs={"foreign_keys": "[Job.customer_id]"})
    assigned_jobs: List[Job] = Relationship(back_populates="assigned_contractor", sa_relationship_kwargs={"foreign_keys": "[Job.assigned_contractor_id]"})
    integrations: List[OmnichannelIntegration] = Relationship(back_populates="contractor")
