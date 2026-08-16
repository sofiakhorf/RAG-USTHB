# config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LIBREOFFICE_PATH: str = "/usr/bin/soffice"
    TESSERACT_LANG_FRA: str = "fra"
    TESSERACT_LANG_ARA: str = "fra+ara"
    MAX_WORKERS: int = 8
    
    class Config:
        env_file = ".env"

settings = Settings()