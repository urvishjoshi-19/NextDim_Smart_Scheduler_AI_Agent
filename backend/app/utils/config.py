from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    deepgram_api_key: str
    gemini_api_key: str
    google_cloud_project: str
    google_application_credentials: Optional[str] = None  # Optional for Cloud Run (uses default credentials)
    google_client_id: str
    google_client_secret: str
    port: int = 8000
    host: str = "0.0.0.0"
    environment: str = "development"
    frontend_url: str = "http://localhost:3000"
    session_secret: str
    redis_url: Optional[str] = None
    default_timezone: str = "Asia/Kolkata"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()

