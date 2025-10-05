# backend/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # TWS Connection
    TWS_HOST: str = "127.0.0.1"
    TWS_PORT: int = 7496
    TWS_CLIENT_ID: int = 1

    # Database
    DATABASE_URL: str = "sqlite:///./portfolio.db"

    # Analytics
    RISK_FREE_RATE: float = 0.05

# Create a single instance to be used throughout the app
settings = Settings()