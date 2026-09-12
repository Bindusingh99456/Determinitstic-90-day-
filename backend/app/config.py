"""
Application Configuration Module
Manages environment variables, default settings, and system parameters.
"""

import os
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    # API Server Settings
    APP_NAME: str = "Buy or Wait? Financial Decision Engine"
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")

    # Gemini AI Configuration
    GEMINI_API_KEY: str = Field(default="", env="GEMINI_API_KEY")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", env="GEMINI_MODEL")

    # Deterministic Financial Parameters
    FORECAST_HORIZON_DAYS: int = Field(default=90, env="FORECAST_HORIZON_DAYS")
    DEFAULT_SAFETY_BUFFER_MINIMUM: float = Field(default=1000.0, env="DEFAULT_SAFETY_BUFFER_MINIMUM")
    DEFAULT_SAFETY_BUFFER_MONTHS: float = Field(default=1.0, env="DEFAULT_SAFETY_BUFFER_MONTHS")
    DEFAULT_DTI_CEILING: float = Field(default=0.36, env="DEFAULT_DTI_CEILING")

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
