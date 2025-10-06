# backend/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List # <-- Add List import

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # TWS Connection
    TWS_HOST: str = "127.0.0.1"
    TWS_PORT: int = 7496
    TWS_CLIENT_ID: int = 1
    TWS_IGNORE_LIST: List[str] = ["MES"] # <-- NEW SETTING

    # Database
    DATABASE_URL: str = "sqlite:///./portfolio.db"

    # Analytics
    RISK_FREE_RATE: float = 0.05

settings = Settings()