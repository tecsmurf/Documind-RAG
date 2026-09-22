from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI Document Intelligence"
    DEBUG: bool = True

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database (PostgreSQL with pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/doc_intelligence"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # RAG Settings
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 5
    MAX_CONTEXT_TOKENS: int = 4000

    # File Upload
    MAX_FILE_SIZE_MB: int = 20
    UPLOAD_DIR: str = "uploads"

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
