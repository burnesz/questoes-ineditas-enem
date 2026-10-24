import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Float, Text, ForeignKey, UUID, DateTime, func, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.ciclo_geracao import CicloGeracao
    from app.db.models.habilidade import HabilidadeEnem
    from app.db.models.questao_inedita import QuestaoInedita

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class TentativaGeracao(Base):
    """
    Armazena os parâmetros de entrada, as variáveis de contexto injetadas e a duração
    de uma tentativa específica (1..N) dentro de um CicloGeracao.
    """
    __tablename__ = "tentativas_geracao"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    ciclo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ciclos_geracao.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    habilidade_codigo: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("habilidades_enem.codigo", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    numero_tentativa: Mapped[int] = mapped_column(Integer, nullable=False)
    modelo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    temperatura: Mapped[float] = mapped_column(Float, nullable=False)
    top_p: Mapped[float] = mapped_column(Float, nullable=False)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tema: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    abertura: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tipologia: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    few_shot_exemplos: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON_TYPE, nullable=True)
    enunciados_recentes: Mapped[Optional[List[str]]] = mapped_column(JSON_TYPE, nullable=True)
    duracao_segundos: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )

    # Relacionamentos
    ciclo: Mapped["CicloGeracao"] = relationship(
        "CicloGeracao",
        back_populates="tentativas"
    )
    habilidade: Mapped["HabilidadeEnem"] = relationship(
        "HabilidadeEnem",
        back_populates="tentativas_geracao"
    )
    questao_saida: Mapped[Optional["QuestaoInedita"]] = relationship(
        "QuestaoInedita",
        back_populates="tentativa",
        uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<TentativaGeracao(id={self.id}, ciclo_id={self.ciclo_id}, "
            f"hab='{self.habilidade_codigo}', num={self.numero_tentativa})>"
        )
