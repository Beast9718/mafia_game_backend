from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Format: postgresql://username:password@host:port/database_name
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:vnq5gkcxnu@localhost:5432/mafia_db"

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