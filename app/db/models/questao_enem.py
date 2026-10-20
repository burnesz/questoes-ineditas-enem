import uuid
from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Text, ForeignKey, UUID, DateTime, func, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.habilidade import HabilidadeEnem

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class QuestaoEnem(Base):
    """
    Acervo histórico original de questões do ENEM (2009-2024) extraídas via arquivo CSV.
    Armazenadas de forma relacional pura para fallback de ancoragem few-shot.
    """
    __tablename__ = "questoes_enem"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    ano: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    habilidade_codigo: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("habilidades_enem.codigo", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    co_item: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    alternativas: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    gabarito: Mapped[str] = mapped_column(String(1), nullable=False)  # 'A', 'B', 'C', 'D', 'E'
    metadados: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relacionamento
    habilidade: Mapped["HabilidadeEnem"] = relationship(
        "HabilidadeEnem",
        back_populates="questoes_enem"
    )

    def __repr__(self) -> str:
        return f"<QuestaoEnem(id={self.id}, ano={self.ano}, hab='{self.habilidade_codigo}')>"
