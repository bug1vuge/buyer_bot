from pydantic import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    ADMIN_CHAT_ID: int
    TELEGRAM_BOT_TOKEN: str
    BUYER_BOT_TOKEN: str

    TINKOFF_TERMINAL_KEY: str
    TINKOFF_PASSWORD: str
    TINKOFF_API_URL: str

    DADATA_API_KEY: str
    BASE_URL: str

    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str

    FRONTEND_RETURN_URL: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
