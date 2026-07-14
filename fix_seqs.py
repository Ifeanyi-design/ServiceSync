import asyncio
from sqlalchemy import text
from app.core.database import engine

async def fix_seqs():
    async with engine.begin() as conn:
        tables = [
            "user", "job", "conversation", "directmessage", "escrow", 
            "review", "paymentmethod", "dispute", "wallettransaction",
            "receipt", "contractorwallet"
        ]
        for table in tables:
            try:
                query = text(f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), coalesce(max(id), 0) + 1, false) FROM \"{table}\";")
                await conn.execute(query)
                print(f"Fixed seq for {table}")
            except Exception as e:
                print(f"Failed {table}: {e}")

if __name__ == "__main__":
    asyncio.run(fix_seqs())
