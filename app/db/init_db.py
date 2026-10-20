import logging
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.habilidade import HabilidadeEnem
from app.db.session import engine
from scripts.seed_habilidades import HABILIDADES_MAT

logger = logging.getLogger("questoes_ineditas.init_db")


def init_db(db: Session) -> None:
    """Cria tabelas no banco de dados e assegura o cadastro inicial das 30 habilidades do ENEM."""
    Base.metadata.create_all(bind=engine)

    count = db.query(HabilidadeEnem).count()
    if count == 0:
        logger.info("Tabela habilidades_enem vazia. Populando as 30 habilidades do ENEM...")
        for item in HABILIDADES_MAT:
            hab = HabilidadeEnem(
                codigo=item["codigo"],
                competencia=item["competencia"],
                descricao=item["descricao"],
                eixo_tematico=item.get("eixo_tematico")
            )
            db.add(hab)
        db.commit()
        logger.info("30 habilidades cadastradas com sucesso.")
    else:
        logger.info(f"Banco já contém {count} habilidades cadastradas.")
