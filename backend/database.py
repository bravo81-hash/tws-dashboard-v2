# backend/database.py
from sqlmodel import create_engine
from config import settings # <-- Import settings

# Use the DATABASE_URL from settings
engine = create_engine(settings.DATABASE_URL, echo=True)