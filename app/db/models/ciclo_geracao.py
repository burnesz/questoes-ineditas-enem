import uuid
from datetime import datetime, timezone
from typing import List, TYPE_CHECKING
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, UUID, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.habilidade import HabilidadeEnem
    from app.db.models.tentativa_geracao import TentativaGeracao
    from app.db.models.questao_inedita import QuestaoInedita


class CicloGeracao(Base):
    """
    Representa um ciclo completo de geração PoT (uma execução de _generate_pot_item
    para produzir uma questão inédita de determinada habilidade com até max_attempts).
    """
    __tablename__ = "ciclos_geracao"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    habilidade_codigo: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("habilidades_enem.codigo", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    total_tentativas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    tempo_total_segundos: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )

    # Relacionamentos
    habilidade: Mapped["HabilidadeEnem"] = relationship(
        "HabilidadeEnem",
        back_populates="ciclos_geracao"
    )
    tentativas: Mapped[List["TentativaGeracao"]] = relationship(
        "TentativaGeracao",
        back_populates="ciclo",
        order_by="TentativaGeracao.numero_tentativa",
        cascade="all, delete-orphan"
    )
    questoes: Mapped[List["QuestaoInedita"]] = relationship(
        "QuestaoInedita",
        back_populates="ciclo",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<CicloGeracao(id={self.id}, hab='{self.habilidade_codigo}', "
            f"tentativas={self.total_tentativas}/{self.max_attempts}, sucesso={self.sucesso})>"
        )
