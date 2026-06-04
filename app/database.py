from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Format: postgresql://username:password@host:port/database_name
# ✅ SAFE
import os
from dotenv import load_dotenv

load_dotenv()

# This tells Python to look in your hidden .env file or Render's vault!
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Notice we removed `connect_args={"check_same_thread": False}` 
# That is only needed for SQLite!
engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency to get the DB session in our API routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()