import os
import sys
import csv
import uuid
import logging
import argparse
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from scripts.seed_habilidades import seed_habilidades

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_questoes")


def parse_csv_rows(csv_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Arquivo CSV não encontrado: {csv_path}")

    items = []
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for line_num, row in enumerate(reader, start=2):
            try:
                co_item = int(row["CO_ITEM"].strip())
                ano = int(row["ANO_APLICACAO"].strip())
                hab_num = int(row["CO_HABILIDADE"].strip())
                hab_code = f"H{hab_num:02d}"
                gabarito = row["TX_GABARITO"].strip().upper()
                enunciado = row["DESC_ENUNCIADO"].strip()

                alternativas = {
                    "A": row["DESC_ALTER_A"].strip(),
                    "B": row["DESC_ALTER_B"].strip(),
                    "C": row["DESC_ALTER_C"].strip(),
                    "D": row["DESC_ALTER_D"].strip(),
                    "E": row["DESC_ALTER_E"].strip(),
                }

                def parse_float(val: Optional[str]) -> Optional[float]:
                    if not val or val.strip() == "":
                        return None
                    try:
                        return float(val.strip().replace(",", "."))
                    except ValueError:
                        return None

                metadados = {
                    "tp_lingua": row.get("TP_LINGUA", "").strip(),
                    "in_item_adaptado": row.get("IN_ITEM_ADAPTADO", "").strip(),
                    "nu_param_a": parse_float(row.get("NU_PARAM_A")),
                    "nu_param_b": parse_float(row.get("NU_PARAM_B")),
                    "nu_param_c": parse_float(row.get("NU_PARAM_C")),
                }

                items.append({
                    "co_item": co_item,
                    "ano": ano,
                    "habilidade_codigo": hab_code,
                    "enunciado": enunciado,
                    "alternativas": alternativas,
                    "gabarito": gabarito,
                    "metadados": metadados,
                })
            except Exception as e:
                logger.warning(f"Erro ao processar linha {line_num}: {e}. Linha ignorada.")
    return items


def seed_questoes(
    csv_path: str = "data/itens_prova_2009_2024_enriquecido.csv",
    db: Optional[Session] = None
) -> Tuple[int, int]:
    should_close = False
    if db is None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        should_close = True
        seed_habilidades(db=db)
    else:
        seed_habilidades(db=db)

    items = parse_csv_rows(csv_path)
    logger.info(f"Lidos {len(items)} itens válidos do CSV.")

    try:
        inserted = 0
        updated = 0
        for item in items:
            existing = db.query(QuestaoEnem).filter(QuestaoEnem.co_item == item["co_item"]).first()
            if existing:
                existing.ano = item["ano"]
                existing.habilidade_codigo = item["habilidade_codigo"]
                existing.enunciado = item["enunciado"]
                existing.alternativas = item["alternativas"]
                existing.gabarito = item["gabarito"]
                existing.metadados = item["metadados"]
                updated += 1
            else:
                novo = QuestaoEnem(
                    id=uuid.uuid4(),
                    co_item=item["co_item"],
                    ano=item["ano"],
                    habilidade_codigo=item["habilidade_codigo"],
                    enunciado=item["enunciado"],
                    alternativas=item["alternativas"],
                    gabarito=item["gabarito"],
                    metadados=item["metadados"]
                )
                db.add(novo)
                inserted += 1
        db.commit()
        logger.info(f"Seed concluído no banco relacional: {inserted} inseridos, {updated} atualizados.")
        return inserted, updated
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed do acervo histórico de questões do ENEM.")
    parser.add_argument("--csv", default="data/itens_prova_2009_2024_enriquecido.csv", help="Caminho do CSV")
    args = parser.parse_args()
    seed_questoes(args.csv)
