import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, UUID, DateTime, Boolean, func, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.ciclo_geracao import CicloGeracao
    from app.db.models.habilidade import HabilidadeEnem
    from app.db.models.tentativa_geracao import TentativaGeracao

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class QuestaoInedita(Base):
    """
    Armazena a saída (output) produzida por uma tentativa de geração PoT,
    tendo sido aprovada em todas as etapas (is_validated=True) ou reprovada (is_validated=False).
    """
    __tablename__ = "questoes_ineditas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    tentativa_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tentativas_geracao.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=True
    )
    ciclo_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ciclos_geracao.id", ondelete="CASCADE"),
        index=True,
        nullable=True
    )
    habilidade_codigo: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("habilidades_enem.codigo", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    enunciado: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alternativas: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True)
    gabarito: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    justificativa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thought_scratchpad: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    etapa_falha: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    codigo_erro: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    motivo_falha: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )

    # Relacionamentos
    habilidade: Mapped["HabilidadeEnem"] = relationship(
        "HabilidadeEnem",
        back_populates="questoes_ineditas"
    )
    tentativa: Mapped[Optional["TentativaGeracao"]] = relationship(
        "TentativaGeracao",
        back_populates="questao_saida"
    )
    ciclo: Mapped[Optional["CicloGeracao"]] = relationship(
        "CicloGeracao",
        back_populates="questoes"
    )

    def __repr__(self) -> str:
        return (
            f"<QuestaoInedita(id={self.id}, hab='{self.habilidade_codigo}', "
            f"valid={self.is_validated}, erro={self.codigo_erro})>"
        )
