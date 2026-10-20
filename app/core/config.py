from functools import lru_cache
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação e parâmetros de execução."""

    PROJECT_NAME: str = "Gerador de Questões Inéditas ENEM"
    VERSION: str = "1.0.0"

    # LLM (Ollama)
    LLM_ENDPOINT_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen2.5:7b-instruct-q4_K_M"
    LLM_TIMEOUT_SECONDS: float = 300.0
    LLM_MAX_TOKENS: int = 1024
    LLM_NUM_CTX: int = 4096

    # Banco Vetorial (ChromaDB)
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_db"
    CHROMA_COLLECTION_QUESTOES: str = "questoes_enem"

    # Embeddings
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large"
    EMBEDDING_DIMENSION: int = 1024
    EMBEDDING_DEVICE: str = "cpu"

    # Complexidade Mínima do Solver
    POT_MIN_OPERATIONS: int = 3
    POT_MIN_OPERATION_TYPES: int = 2

    # Banco Relacional (SQLite padrão / PostgreSQL opcional)
    DATABASE_URL: Optional[str] = None
    POSTGRES_SERVER: Optional[str] = None
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_DB: Optional[str] = None
    POSTGRES_PORT: int = 5432

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        """Define SQLite como banco padrão em './questoes_ineditas.db' ou monta conexão PostgreSQL."""
        if not self.DATABASE_URL:
            if self.POSTGRES_SERVER and self.POSTGRES_USER and self.POSTGRES_DB:
                self.DATABASE_URL = (
                    f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD or ''}"
                    f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
                )
            else:
                self.DATABASE_URL = "sqlite:///./questoes_ineditas.db"
        elif self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
