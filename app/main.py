from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .models import models 
from .api import auth, websocket # Import both routers now

# Create the database tables in PostgreSQL
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mafia: Night Has Come Engine")

# Allow the Flutter app to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register the routes
app.include_router(auth.router)
app.include_router(websocket.router)

@app.get("/")
def read_root():
    return {"status": "The Puppet Master is awake.", "database": "PostgreSQL Connected"}