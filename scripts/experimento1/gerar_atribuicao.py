"""
Experimento 1 — Fase 0.2: matriz de atribuição (tipo de erro × LLM adulterador).

Para cada questão autêntica da amostra, define qual defeito será inserido e qual LLM
fará a adulteração. A atribuição é determinística (seed fixa) e balanceada:
- cada tipo de erro recebe 35 itens e cada habilidade recebe os 4 tipos (+1 extra);
- cada LLM recebe 46-47 itens, com cruzamento tipo × LLM de 11-12 itens.
"""
import os
import csv
import random
import logging
import argparse
from collections import Counter, defaultdict
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gerar_atribuicao")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_INPUT = os.path.join(ROOT, "data", "experimento1", "amostra_140_historicas.csv")
DEFAULT_OUTPUT = os.path.join(ROOT, "data", "experimento1", "atribuicao.csv")

TIPOS_ERRO = ["GABARITO", "CALCULO", "AMBIGUIDADE", "CONTRADICAO"]
LLMS_ADULTERADORES = ["gpt", "deepseek", "gemini"]
DEFAULT_SEED = 20261025


def load_amostra(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def atribuir_tipos(itens: List[Dict[str, str]], rng: random.Random) -> Dict[str, str]:
    """Garante os 4 tipos em cada habilidade; os itens excedentes giram entre os tipos."""
    por_hab: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for item in itens:
        por_hab[item["habilidade_codigo"]].append(item)

    habilidades = sorted(por_hab)
    rng.shuffle(habilidades)
    extras = [TIPOS_ERRO[i % len(TIPOS_ERRO)] for i in range(len(habilidades))]

    tipo_por_id: Dict[str, str] = {}
    for hab, extra in zip(habilidades, extras):
        grupo = por_hab[hab][:]
        rng.shuffle(grupo)
        tipos = TIPOS_ERRO[:]
        tipos += [extra] * (len(grupo) - len(tipos))
        rng.shuffle(tipos)
        for item, tipo in zip(grupo, tipos):
            tipo_por_id[item["id"]] = tipo
    return tipo_por_id


def atribuir_llms(tipo_por_id: Dict[str, str], rng: random.Random) -> Dict[str, str]:
    """Distribui cada tipo entre os LLMs em rodízio contínuo, mantendo os totais equilibrados."""
    por_tipo: Dict[str, List[str]] = defaultdict(list)
    for item_id, tipo in tipo_por_id.items():
        por_tipo[tipo].append(item_id)

    llm_por_id: Dict[str, str] = {}
    cursor = 0
    for tipo in TIPOS_ERRO:
        ids = sorted(por_tipo[tipo])
        rng.shuffle(ids)
        for item_id in ids:
            llm_por_id[item_id] = LLMS_ADULTERADORES[cursor % len(LLMS_ADULTERADORES)]
            cursor += 1
    return llm_por_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera a matriz de atribuição do Experimento 1.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    itens = load_amostra(args.input)
    rng = random.Random(args.seed)
    tipo_por_id = atribuir_tipos(itens, rng)
    llm_por_id = atribuir_llms(tipo_por_id, rng)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    campos = ["id", "habilidade_codigo", "ano", "co_item", "gabarito_original", "tipo_erro", "llm_adulterador"]
    with open(args.output, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for item in sorted(itens, key=lambda x: (x["habilidade_codigo"], x["id"])):
            writer.writerow({
                "id": item["id"],
                "habilidade_codigo": item["habilidade_codigo"],
                "ano": item["ano"],
                "co_item": item["co_item"],
                "gabarito_original": item["gabarito"],
                "tipo_erro": tipo_por_id[item["id"]],
                "llm_adulterador": llm_por_id[item["id"]],
            })

    cruzamento = Counter((tipo_por_id[i], llm_por_id[i]) for i in tipo_por_id)
    logger.info(f"{len(itens)} itens atribuídos (seed={args.seed}) → {args.output}")
    logger.info(f"Por tipo: {dict(Counter(tipo_por_id.values()))}")
    logger.info(f"Por LLM: {dict(Counter(llm_por_id.values()))}")
    for tipo in TIPOS_ERRO:
        logger.info(f"  {tipo:<13} " + "  ".join(f"{llm}={cruzamento[(tipo, llm)]}" for llm in LLMS_ADULTERADORES))


if __name__ == "__main__":
    main()
