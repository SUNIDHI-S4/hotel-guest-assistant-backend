from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    supabase_url: str
    supabase_key: str
    default_hotel_id: str

    # The guide names gemini-2.5-flash, but Google no longer serves it to new API keys (404) and
    # points to gemini-3.6-flash as its replacement.
    gemini_model: str = "gemini-3.6-flash"
    gemini_timeout_seconds: float = 15.0

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    # Timezone the hotel operates in; decides what "today" means for date validation.
    hotel_timezone: str = "Asia/Kolkata"
    # Prices in the database carry no currency; this is shown in front of them.
    currency_symbol: str = "₹"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
