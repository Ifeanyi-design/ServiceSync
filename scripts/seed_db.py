import asyncio
import os
import sys
from pathlib import Path

# Add the project root to sys.path so we can import 'app'
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session_maker
from app.core.security import get_password_hash
from app.models.all_models import User

async def seed_db():
    print("Starting database seeding...")
    
    # Pre-hashed password for "password123" to save time
    default_password = get_password_hash("password123")
    
    contractors = [
        User(
            email="mike@plumbingpros.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Mike's Plumbing",
            phone="555-0101",
            zip_code="90210",
            profession="plumber",
            service_radius_miles=20,
            base_pricing=120.0,
            max_daily_jobs=6,
            working_hours_start="07:00",
            working_hours_end="17:00",
            ai_tone_preference="professional"
        ),
        User(
            email="sarah@sparkyelectric.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Sarah the Sparky",
            phone="555-0102",
            zip_code="90211",
            profession="electrician",
            service_radius_miles=30,
            base_pricing=150.0,
            max_daily_jobs=4,
            working_hours_start="08:00",
            working_hours_end="18:00",
            ai_tone_preference="friendly"
        ),
        User(
            email="joe@hvacmasters.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Joe's HVAC Masters",
            phone="555-0103",
            zip_code="90212",
            profession="hvac",
            service_radius_miles=50,
            base_pricing=85.0,
            max_daily_jobs=8,
            working_hours_start="06:00",
            working_hours_end="20:00",
            ai_tone_preference="direct"
        ),
        User(
            email="emily@elitecleaners.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Elite Home Cleaning",
            phone="555-0104",
            zip_code="90210",
            profession="cleaner",
            service_radius_miles=15,
            base_pricing=60.0,
            max_daily_jobs=3,
            working_hours_start="09:00",
            working_hours_end="16:00",
            ai_tone_preference="warm and professional"
        ),
        User(
            email="tony@topnotchroofing.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Top Notch Roofing",
            phone="555-0105",
            zip_code="90215",
            profession="roofer",
            service_radius_miles=40,
            base_pricing=250.0,
            max_daily_jobs=2,
            working_hours_start="07:00",
            working_hours_end="15:00",
            ai_tone_preference="authoritative"
        )
    ]
    
    customers = [
        User(
            email="john.doe@example.com",
            hashed_password=default_password,
            role="customer",
            full_name="John Doe",
            phone="555-0201",
            zip_code="90210"
        ),
        User(
            email="jane.smith@example.com",
            hashed_password=default_password,
            role="customer",
            full_name="Jane Smith",
            phone="555-0202",
            zip_code="90211"
        ),
        User(
            email="admin@servicesync.com",
            hashed_password=default_password,
            role="admin",
            full_name="System Admin",
        )
    ]
    
    all_users = contractors + customers
    
    async with async_session_maker() as db:
        from sqlmodel import select
        
        added = 0
        for user in all_users:
            # Check if user exists
            existing = await db.exec(select(User).where(User.email == user.email))
            if not existing.first():
                db.add(user)
                added += 1
                
        if added > 0:
            await db.commit()
            print(f"Successfully seeded {added} users!")
        else:
            print("Database already seeded with these users.")

if __name__ == "__main__":
    asyncio.run(seed_db())
