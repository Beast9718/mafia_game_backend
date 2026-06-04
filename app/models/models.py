from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from ..database import Base

class GamePhase(str, enum.Enum):
    LOBBY = "LOBBY"
    ROLE_ASSIGNMENT = "ROLE_ASSIGNMENT"
    DAY = "DAY"
    NIGHT = "NIGHT"
    FINISHED = "FINISHED"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # A user can be in multiple game instances over time
    players = relationship("Player", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_code = Column(String(10), unique=True, index=True, nullable=False) # e.g., D3AD-N1T3
    phase = Column(Enum(GamePhase), default=GamePhase.LOBBY)
    host_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    players = relationship("Player", back_populates="room", cascade="all, delete-orphan")

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Game State
    role = Column(String, nullable=True) # MAFIA, COP, DOCTOR, STUDENT
    is_alive = Column(Boolean, default=True)
    is_host = Column(Boolean, default=False)
    
    # Optional: Cache the image path if you want to store it in the DB later
    profile_image_path = Column(String, nullable=True) 

    room = relationship("Room", back_populates="players")
    user = relationship("User", back_populates="players")