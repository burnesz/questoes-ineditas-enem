import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.habilidade import HabilidadeEnem
from app.db.session import engine
from scripts.seed_habilidades import HABILIDADES_MAT

logger = logging.getLogger("questoes_ineditas.init_db")


def _migrate_questoes_ineditas_if_needed(db: Session) -> None:
    """
    Garante que bancos SQLite existentes possuam as novas colunas de rastreabilidade
    em 'questoes_ineditas' e permitam NULL em 'enunciado', 'alternativas', 'gabarito' e 'justificativa'
    para armazenar saídas parciais de tentativas reprovadas.
    """
    try:
        old_exists = db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='_questoes_ineditas_old'")
        ).fetchone()
        rows = db.execute(text("PRAGMA table_info(questoes_ineditas)")).fetchall()
        if not rows and not old_exists:
            return

        col_map = {row[1]: {"notnull": bool(row[3])} for row in rows}
        needs_rebuild = (
            bool(old_exists)
            or "tentativa_id" not in col_map
            or "ciclo_id" not in col_map
            or "etapa_falha" not in col_map
            or "codigo_erro" not in col_map
            or "motivo_falha" not in col_map
            or col_map.get("enunciado", {}).get("notnull", False)
            or col_map.get("alternativas", {}).get("notnull", False)
            or col_map.get("gabarito", {}).get("notnull", False)
            or col_map.get("justificativa", {}).get("notnull", False)
        )
        if not needs_rebuild:
            return

        logger.info("Migrando schema da tabela 'questoes_ineditas' para suportar saídas de todas as tentativas...")
        if not old_exists:
            db.execute(text("ALTER TABLE questoes_ineditas RENAME TO _questoes_ineditas_old"))
        else:
            db.execute(text("DROP TABLE IF EXISTS questoes_ineditas"))

        # Remove índices antigos para evitar conflito no SQLite ao recriar a tabela
        idx_rows = db.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_questoes_ineditas_%'")
        ).fetchall()
        for (idx_name,) in idx_rows:
            db.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        db.commit()

        bind = db.get_bind() or engine
        Base.metadata.tables["questoes_ineditas"].create(bind=bind, checkfirst=True)

        old_cols_rows = db.execute(text("PRAGMA table_info(_questoes_ineditas_old)")).fetchall()
        old_col_names = {r[1] for r in old_cols_rows}

        shared_cols = [
            col for col in [
                "id",
                "tentativa_id",
                "ciclo_id",
                "habilidade_codigo",
                "enunciado",
                "alternativas",
                "gabarito",
                "justificativa",
                "thought_scratchpad",
                "is_validated",
                "etapa_falha",
                "codigo_erro",
                "motivo_falha",
                "created_at",
            ]
            if col in old_col_names
        ]
        cols_csv = ", ".join(shared_cols)
        db.execute(
            text(f"INSERT OR IGNORE INTO questoes_ineditas ({cols_csv}) SELECT {cols_csv} FROM _questoes_ineditas_old")
        )
        db.execute(text("DROP TABLE _questoes_ineditas_old"))
        db.commit()
        logger.info("Tabela 'questoes_ineditas' migrada com sucesso.")
    except Exception as e:
        db.rollback()
        logger.warning(f"Aviso ao verificar/migrar schema de 'questoes_ineditas': {e}")


_ETAPA_FALHA_RENOMEADAS = {
    "1a_planejamento": "2a_planejamento",
    "1b_solver": "2b_solver",
    "5.1_resolucao_cega": "4.1_resolucao_cega",
    "5.1_nao_respondivel": "4.1_nao_respondivel",
    "5.1_premissa_oculta": "4.1_premissa_oculta",
    "5.1_dados_ociosos": "4.1_dados_ociosos",
    "5.2_equivalencia": "4.2_equivalencia",
    "5.3_auditoria_b3": "4.3_auditoria_pedagogica",
}


def _migrate_etapa_falha_labels(db: Session) -> None:
    """
    Converte os rótulos de 'etapa_falha' gravados com a numeração antiga do pipeline
    (Fases 1a/1b, Validação 5.x, auditoria 'b3') para a numeração atual em 5 etapas.
    """
    try:
        for antigo, novo in _ETAPA_FALHA_RENOMEADAS.items():
            db.execute(
                text("UPDATE questoes_ineditas SET etapa_falha = :novo WHERE etapa_falha = :antigo"),
                {"novo": novo, "antigo": antigo}
            )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Aviso ao migrar rótulos de 'etapa_falha' em 'questoes_ineditas': {e}")


def init_db(db: Session) -> None:
    """Cria tabelas no banco de dados e assegura o cadastro inicial das 30 habilidades do ENEM."""
    bind = db.get_bind() or engine
    Base.metadata.create_all(bind=bind)
    _migrate_questoes_ineditas_if_needed(db)
    _migrate_etapa_falha_labels(db)

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
