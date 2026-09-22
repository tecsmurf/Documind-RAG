from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI Document Intelligence"
    DEBUG: bool = True

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database (PostgreSQL with pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/doc_intelligence"

    # Google Gemini (FREE tier)
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSIONS: int = 768  # Gemini text-embedding-004 outputs 768-dim vectors

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
