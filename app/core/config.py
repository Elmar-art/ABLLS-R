from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./ablls.db"

    class Config:
        env_file = ".env"


settings = Settings()
