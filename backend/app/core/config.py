from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OPENPROJECT_")

    database_url: str = "postgresql+asyncpg://openproject:openproject@localhost:5432/openproject"

    ollama_host: str = "http://localhost:11434"
    ollama_timeout_seconds: float = 120.0
    llm_model: str = "qwen2.5:14b-instruct"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    extraction_max_chars: int = 12000
    chat_retrieval_limit: int = 5
    chat_history_max_chars: int = 4000

    cors_allow_origins: str = "*"  # safe only when the backend listens on localhost; restrict if exposing to a network

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_sql_queries: bool = False
    log_llm_interactions: bool = True
    log_llm_preview_chars: int = 200


settings = Settings()
