import sys
import os
from app.core.config import settings
from sqlalchemy import create_engine, text

def reset_database():
    print(f"Connecting to: {settings.SQLALCHEMY_DATABASE_URI}")
    engine = create_engine(settings.SQLALCHEMY_DATABASE_URI)
    
    with engine.connect() as conn:
        print("Dropping schema public...")
        conn.execute(text("DROP SCHEMA public CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        conn.execute(text("COMMENT ON SCHEMA public IS 'standard public schema';"))
        conn.commit()
        print("Done: Database reset successfully.")

if __name__ == "__main__":
    confirm = input("Are you sure you want to WIPE the CLOUD database? (y/n): ")
    if confirm.lower() == 'y':
        reset_database()
    else:
        print("Aborted.")
