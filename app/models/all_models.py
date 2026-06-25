from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, JSON, Numeric
from datetime import datetime
from decimal import Decimal


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
    customer: "User" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Conversation.customer_id]"})
    contractor: "User" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Conversation.contractor_id]"})


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
    ai_autonomy_level: int = Field(default=1)  # 1=manual, 2=AI drafts, 3=auto-reply
    trade_qualifications: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # Verification and reputation
    verification_level: Optional[str] = Field(default=None) # Bronze, Silver, Gold, Verified Pro
    reputation_score: Optional[float] = Field(default=None) # e.g., 4.9
    availability_status: Optional[str] = Field(default="Available") # Available, Busy, Away, Vacation
    
    jobs: List[Job] = Relationship(back_populates="customer", sa_relationship_kwargs={"foreign_keys": "[Job.customer_id]"})
    assigned_jobs: List[Job] = Relationship(back_populates="assigned_contractor", sa_relationship_kwargs={"foreign_keys": "[Job.assigned_contractor_id]"})
    integrations: List[OmnichannelIntegration] = Relationship(back_populates="contractor")
    reviews: List["Review"] = Relationship(back_populates="contractor")


class Review(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    contractor_id: int = Field(foreign_key="user.id")
    rating: int = Field(ge=1, le=5) # 1 to 5 stars
    comment: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    job: "Job" = Relationship()
    contractor: "User" = Relationship(back_populates="reviews")


class Escrow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", unique=True)
    customer_id: int = Field(foreign_key="user.id")
    contractor_id: int = Field(foreign_key="user.id")
    
    # Financial fields — use Decimal for money
    total_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2)))
    platform_fee: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2)))
    contractor_payout: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2)))
    customer_refund: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2)))
    
    # Status: held, released, refunded, penalty_split, disputed
    status: str = Field(default="held")
    
    # Gateway references
    payment_gateway_id: Optional[str] = None
    payout_reference_id: Optional[str] = None
    currency: str = Field(default="USD")
    
    # Timestamps
    funded_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    job: "Job" = Relationship()
    customer: "User" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Escrow.customer_id]"})
    contractor: "User" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Escrow.contractor_id]"})
    dispute: Optional["Dispute"] = Relationship(back_populates="escrow")


class Dispute(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    escrow_id: int = Field(foreign_key="escrow.id", unique=True)
    job_id: int = Field(foreign_key="job.id")
    raised_by: int = Field(foreign_key="user.id")
    
    reason: str
    status: str = Field(default="pending_ai")  # pending_ai, reviewing, resolved
    
    # AI arbitration
    ai_arbitration_summary: Optional[str] = None
    ai_recommended_refund_pct: Optional[float] = None  # 0-100
    
    # Resolution
    resolution_notes: Optional[str] = None
    resolved_by: Optional[int] = Field(default=None, foreign_key="user.id")
    resolved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    escrow: "Escrow" = Relationship(back_populates="dispute")
    job: "Job" = Relationship()
    raiser: "User" = Relationship(sa_relationship_kwargs={"foreign_keys": "[Dispute.raised_by]"})


class AIDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    contractor_id: int = Field(foreign_key="user.id")
    content: str
    status: str = Field(default="pending")  # pending, approved, dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None