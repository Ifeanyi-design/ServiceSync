import asyncio
import os
import sys
from pathlib import Path

# Add the project root to sys.path so we can import 'app'
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session_maker
from app.core.security import get_password_hash
from app.models.all_models import User, Job, Review, Conversation
from app.core.config import settings
from app.core.migrate import run_migration

async def seed_db():
    # Ensure the schema is in sync (adds any new tables/columns) before we read
    # or write any rows — this is what makes deploys safe even if the build
    # command doesn't explicitly run the migration.
    await run_migration()

    # Never seed demo data (including the well-known admin@servicesync.com /
    # password123 account) into a real deployment. Set DEMO_MODE=true in
    # non-production environments only.
    if not settings.DEMO_MODE:
        print("DEMO_MODE is disabled — skipping demo seed (no demo users/jobs created).")
        return

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
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="Beverly Hills",
            postal_code="90210",
            latitude=34.0736,
            longitude=-118.4004,
            profession="plumber",
            service_radius_miles=20,
            base_pricing=120.0,
            max_daily_jobs=6,
            working_hours_start="07:00",
            working_hours_end="17:00",
            ai_tone_preference="professional",
            verification_level="gold",
            reputation_score=4.8,
            availability_status="Available",
        ),
        User(
            email="sarah@sparkyelectric.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Sarah the Sparky",
            phone="555-0102",
            zip_code="90211",
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="West Hollywood",
            postal_code="90211",
            latitude=34.0907,
            longitude=-118.3766,
            profession="electrician",
            service_radius_miles=30,
            base_pricing=150.0,
            max_daily_jobs=4,
            working_hours_start="08:00",
            working_hours_end="18:00",
            ai_tone_preference="friendly",
            verification_level="verified pro",
            reputation_score=4.9,
            availability_status="Available",
        ),
        User(
            email="joe@hvacmasters.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Joe's HVAC Masters",
            phone="555-0103",
            zip_code="90212",
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="Beverly Hills",
            postal_code="90212",
            latitude=34.0697,
            longitude=-118.3985,
            profession="hvac",
            service_radius_miles=50,
            base_pricing=85.0,
            max_daily_jobs=8,
            working_hours_start="06:00",
            working_hours_end="20:00",
            ai_tone_preference="direct",
            verification_level="silver",
            reputation_score=4.5,
            availability_status="Available",
        ),
        User(
            email="emily@elitecleaners.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Elite Home Cleaning",
            phone="555-0104",
            zip_code="90210",
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="Beverly Hills",
            postal_code="90210",
            latitude=34.0736,
            longitude=-118.4004,
            profession="cleaner",
            service_radius_miles=15,
            base_pricing=60.0,
            max_daily_jobs=3,
            working_hours_start="09:00",
            working_hours_end="16:00",
            ai_tone_preference="warm and professional",
            verification_level="bronze",
            reputation_score=4.2,
            availability_status="Available",
        ),
        User(
            email="tony@topnotchroofing.com",
            hashed_password=default_password,
            role="contractor",
            full_name="Top Notch Roofing",
            phone="555-0105",
            zip_code="90215",
            country="United States",
            state_or_province="California",
            city="Los Angeles",
            area="Downtown",
            postal_code="90015",
            latitude=34.0407,
            longitude=-118.2468,
            profession="roofer",
            service_radius_miles=40,
            base_pricing=250.0,
            max_daily_jobs=2,
            working_hours_start="07:00",
            working_hours_end="15:00",
            ai_tone_preference="authoritative",
            verification_level="gold",
            reputation_score=4.7,
            availability_status="Busy",
        ),
        User(
            email="securecam@lagoscctv.ng",
            hashed_password=default_password,
            role="contractor",
            full_name="SecureCam CCTV & Security",
            phone="+234-802-111-2233",
            country="Nigeria",
            state_or_province="Lagos",
            city="Lagos",
            area="Ikeja",
            postal_code="100001",
            latitude=6.5244,
            longitude=3.3792,
            profession="cctv",
            specialties=["CCTV", "security cameras", "night vision", "remote viewing", "surveillance"],
            service_radius_miles=60,
            base_pricing=90.0,
            max_daily_jobs=5,
            working_hours_start="08:00",
            working_hours_end="19:00",
            ai_tone_preference="professional",
            verification_level="gold",
            reputation_score=4.9,
            availability_status="Available",
        ),
        User(
            email="sunpower@solarenergy.ng",
            hashed_password=default_password,
            role="contractor",
            full_name="SunPower Solar Installers",
            phone="+234-803-444-5566",
            country="Nigeria",
            state_or_province="Lagos",
            city="Lagos",
            area="Lekki",
            postal_code="105102",
            latitude=6.4432,
            longitude=3.4710,
            profession="solar",
            specialties=["Solar panels", "inverters", "solar installation", "battery storage"],
            service_radius_miles=80,
            base_pricing=200.0,
            max_daily_jobs=3,
            working_hours_start="08:00",
            working_hours_end="17:00",
            ai_tone_preference="friendly",
            verification_level="verified pro",
            reputation_score=4.8,
            availability_status="Available",
        ),
        # Global test contractors
        User(
            email="ade@lagosplumbing.ng",
            hashed_password=default_password,
            role="contractor",
            full_name="Ade's Plumbing Services",
            phone="+234-801-234-5678",
            country="Nigeria",
            state_or_province="Lagos",
            city="Lagos",
            area="Ikeja",
            postal_code="100001",
            latitude=6.6000,
            longitude=3.3500,
            profession="plumber",
            service_radius_miles=25,
            base_pricing=15000.0,
            max_daily_jobs=5,
            working_hours_start="08:00",
            working_hours_end="18:00",
            ai_tone_preference="friendly",
            verification_level="gold",
            reputation_score=4.7,
            availability_status="Available",
        ),
        User(
            email="chidi@lagoselectric.ng",
            hashed_password=default_password,
            role="contractor",
            full_name="Chidi Electric Solutions",
            phone="+234-802-345-6789",
            country="Nigeria",
            state_or_province="Lagos",
            city="Lagos",
            area="Lekki",
            postal_code="101001",
            latitude=6.4478,
            longitude=3.4564,
            profession="electrician",
            service_radius_miles=30,
            base_pricing=20000.0,
            max_daily_jobs=4,
            working_hours_start="07:00",
            working_hours_end="19:00",
            ai_tone_preference="professional",
            verification_level="silver",
            reputation_score=4.4,
            availability_status="Available",
        ),
        User(
            email="james@londonplumbing.co.uk",
            hashed_password=default_password,
            role="contractor",
            full_name="James & Sons Plumbing",
            phone="+44-20-7946-0958",
            country="United Kingdom",
            state_or_province="England",
            city="London",
            area="Westminster",
            postal_code="SW1A 1AA",
            latitude=51.5014,
            longitude=-0.1419,
            profession="plumber",
            service_radius_miles=20,
            base_pricing=85.0,
            max_daily_jobs=6,
            working_hours_start="08:00",
            working_hours_end="17:00",
            ai_tone_preference="professional",
            verification_level="verified pro",
            reputation_score=4.9,
            availability_status="Available",
        ),
        User(
            email="priya@newdelhihomes.in",
            hashed_password=default_password,
            role="contractor",
            full_name="Priya Home Services",
            phone="+91-11-2345-6789",
            country="India",
            state_or_province="Delhi",
            city="New Delhi",
            area="Connaught Place",
            postal_code="110001",
            latitude=28.6315,
            longitude=77.2167,
            profession="cleaner",
            service_radius_miles=15,
            base_pricing=500.0,
            max_daily_jobs=4,
            working_hours_start="09:00",
            working_hours_end="18:00",
            ai_tone_preference="warm and professional",
            verification_level="bronze",
            reputation_score=4.3,
            availability_status="Available",
        ),
    ]
    
    customers = [
        User(
            email="john.doe@example.com",
            hashed_password=default_password,
            role="customer",
            full_name="John Doe",
            phone="555-0201",
            zip_code="90210",
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="Beverly Hills",
            postal_code="90210",
            latitude=34.0736,
            longitude=-118.4004,
        ),
        User(
            email="jane.smith@example.com",
            hashed_password=default_password,
            role="customer",
            full_name="Jane Smith",
            phone="555-0202",
            zip_code="90211",
            country="United States",
            state_or_province="California",
            city="Beverly Hills",
            area="West Hollywood",
            postal_code="90211",
            latitude=34.0907,
            longitude=-118.3766,
        ),
        User(
            email="fatima@lagoscustomer.ng",
            hashed_password=default_password,
            role="customer",
            full_name="Fatima Abubakar",
            phone="+234-803-456-7890",
            country="Nigeria",
            state_or_province="Lagos",
            city="Lagos",
            area="Ikeja",
            postal_code="100001",
            latitude=6.6000,
            longitude=3.3500,
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

        # --- Seed Jobs and Reviews for Demo ---
        from datetime import datetime, timedelta
        
        c_mike = await db.exec(select(User).where(User.email == "mike@plumbingpros.com"))
        mike = c_mike.first()
        c_sarah = await db.exec(select(User).where(User.email == "sarah@sparkyelectric.com"))
        sarah = c_sarah.first()
        c_joe = await db.exec(select(User).where(User.email == "joe@hvacmasters.com"))
        joe = c_joe.first()
        
        c_john = await db.exec(select(User).where(User.email == "john.doe@example.com"))
        john = c_john.first()
        
        if john and mike and sarah and joe:
            # Check if jobs exist
            existing_jobs = await db.exec(select(Job).where(Job.customer_id == john.id))
            if not existing_jobs.first():
                print("Seeding Demo Jobs and Reviews...")
                
                j1 = Job(customer_id=john.id, assigned_contractor_id=mike.id, description="Kitchen sink is leaking under the cabinet", status="completed", urgency="medium", created_at=datetime.utcnow() - timedelta(days=2))
                j2 = Job(customer_id=john.id, assigned_contractor_id=sarah.id, description="Power outlet in living room is sparking", status="completed", urgency="high", created_at=datetime.utcnow() - timedelta(days=5))
                j3 = Job(customer_id=john.id, assigned_contractor_id=joe.id, description="AC is blowing warm air", status="in_progress", urgency="high", created_at=datetime.utcnow())
                db.add_all([j1, j2, j3])
                await db.commit()
                await db.refresh(j1)
                await db.refresh(j2)
                await db.refresh(j3)
                
                # Conversations
                conv1 = Conversation(job_id=j1.id, customer_id=john.id, contractor_id=mike.id)
                conv2 = Conversation(job_id=j2.id, customer_id=john.id, contractor_id=sarah.id)
                conv3 = Conversation(job_id=j3.id, customer_id=john.id, contractor_id=joe.id)
                db.add_all([conv1, conv2, conv3])
                
                # Reviews
                r1 = Review(job_id=j1.id, contractor_id=mike.id, rating=5, comment="Mike was super fast and fixed the leak in 10 minutes. Highly recommend!", created_at=datetime.utcnow() - timedelta(days=1))
                r2 = Review(job_id=j2.id, contractor_id=sarah.id, rating=5, comment="Sarah is amazing. Very safe and professional.", created_at=datetime.utcnow() - timedelta(days=4))
                db.add_all([r1, r2])
                await db.commit()
                print("Successfully seeded Jobs, Conversations, and Reviews.")
            else:
                print("Jobs already exist for John.")
        else:
            print(f"Users missing! John={john} Mike={mike} Sarah={sarah} Joe={joe}")

if __name__ == "__main__":
    asyncio.run(seed_db())
