from typing import List, Union
from pydantic import AnyHttpUrl, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Check Phone Scam API"
    PORT: int = 8000

    
    # BACKEND_CORS_ORIGINS is a JSON-formatted list of strings
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000"]'
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    SECRET_KEY: str = "change-this-secret-key-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    SQLALCHEMY_DATABASE_URI: str = "postgresql://postgres:postgres@localhost:5432/db"
    FIREBASE_CREDENTIALS_PATH: str = "firebase-adminsdk.json"
    FIREBASE_CREDENTIALS_JSON: str = ""
    HF_TOKEN: str = ""
    HF_API_URL: str = "huhuhu"
    GEMINI_API_KEY: str = ""
    TEST_API_BASE_URL: str = "http://localhost:8000/api/v1"

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"

settings = Settings()
