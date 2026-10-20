from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.questao_enem import QuestaoEnem
    from app.db.models.questao_inedita import QuestaoInedita


class HabilidadeEnem(Base):
    """
    Matriz de Referência de Matemática do ENEM: 30 habilidades (H01 a H30)
    distribuídas nas 7 Competências de Área do INEP.
    """
    __tablename__ = "habilidades_enem"

    codigo: Mapped[str] = mapped_column(String(10), primary_key=True)  # Ex: 'H01' ... 'H30'
    competencia: Mapped[int] = mapped_column(Integer, nullable=False)   # 1 a 7
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    eixo_tematico: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relacionamentos
    questoes_enem: Mapped[List["QuestaoEnem"]] = relationship(
        "QuestaoEnem",
        back_populates="habilidade"
    )
    questoes_ineditas: Mapped[List["QuestaoInedita"]] = relationship(
        "QuestaoInedita",
        back_populates="habilidade"
    )

    def __repr__(self) -> str:
        return f"<HabilidadeEnem(codigo='{self.codigo}', comp={self.competencia})>"
