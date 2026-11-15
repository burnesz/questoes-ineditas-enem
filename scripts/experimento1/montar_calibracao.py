"""
Experimento 1 — conjunto de calibração da pipeline (fora da base de teste).

Sorteia questões autênticas da tabela questoes_enem (as mesmas fontes da amostra: Matemática, só texto,
sem H06/H20) que NÃO estão na amostra de 140, nem com o mesmo co_item nem com o mesmo enunciado.
Serve para validar mudanças na Etapa 4 sem ajustá-la aos itens da base de teste.

Grava data/experimento1/calibracao.jsonl no mesmo formato de base_experimento.jsonl
(item_id cal_NNN), pronto para:
    python scripts/experimento1/avaliar_base.py --modelo <tag> --base data/experimento1/calibracao.jsonl

Uso:
    python scripts/experimento1/montar_calibracao.py [--n 30] [--semente 7]
"""
import os
import csv
import json
import random
import sqlite3
import argparse

from prompt_adulteracao import DEFAULT_AMOSTRA, ROOT

DIR_EXP = os.path.join(ROOT, "data", "experimento1")
DEFAULT_DB = os.path.join(ROOT, "questoes_ineditas.db")
DEFAULT_SAIDA = os.path.join(DIR_EXP, "calibracao.jsonl")


def normalizar(texto: str) -> str:
    return " ".join((texto or "").lower().split())


def main() -> None:
    parser = argparse.ArgumentParser(description="Sorteia o conjunto de calibração do Experimento 1.")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--semente", type=int, default=7)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--saida", default=DEFAULT_SAIDA)
    args = parser.parse_args()

    with open(DEFAULT_AMOSTRA, encoding="utf-8-sig") as f:
        amostra = list(csv.DictReader(f))
    itens_amostra = {str(r["co_item"]) for r in amostra}
    enunciados_amostra = {normalizar(r["enunciado"]) for r in amostra}

    con = sqlite3.connect(args.db)
    linhas = con.execute(
        "SELECT co_item, habilidade_codigo, ano, enunciado, alternativas, gabarito FROM questoes_enem ORDER BY co_item"
    ).fetchall()
    candidatos, vistos = [], set()
    for co_item, hab, ano, enunciado, alternativas, gabarito in linhas:
        chave = normalizar(enunciado)
        if str(co_item) in itens_amostra or chave in enunciados_amostra or chave in vistos:
            continue
        vistos.add(chave)
        candidatos.append({
            "id_original": str(co_item), "habilidade_codigo": hab, "ano": str(ano),
            "enunciado": enunciado, "alternativas": json.loads(alternativas), "gabarito": gabarito,
        })

    sorteados = random.Random(args.semente).sample(candidatos, args.n)
    with open(args.saida, "w", encoding="utf-8") as f:
        for n, item in enumerate(sorteados, start=1):
            f.write(json.dumps({"item_id": f"cal_{n:03d}", **item}, ensure_ascii=False) + "\n")

    print(f"{len(candidatos)} candidatos fora da amostra; {args.n} sorteados (semente {args.semente}) → "
          f"{os.path.relpath(args.saida, ROOT)}")


if __name__ == "__main__":
    main()
