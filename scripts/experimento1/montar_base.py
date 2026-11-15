"""
Experimento 1 — Fases 1.3 e 2.6: monta a base que os modelos avaliadores vão receber.

Lê a amostra (versões autênticas, já corrigidas) e data/experimento1/modificadas.jsonl
(gerado por consolidar_revisao.py) e grava:

- data/experimento1/autenticas.jsonl           → 140 itens com rotulo="autentica"
- data/experimento1/base_experimento.jsonl     → autênticas + modificadas embaralhadas, com
  identificador opaco e só os campos que o avaliador pode ver
- data/experimento1/base_experimento_chave.csv → identificador opaco → item original,
  rótulo, tipo de erro, LLM adulterador e ajuste manual (nunca mostrar ao avaliador)

Uso:
    python scripts/experimento1/montar_base.py [--semente 42]
"""
import os
import json
import random
import argparse
import csv

from prompt_adulteracao import DEFAULT_AMOSTRA, ROOT

DIR_EXP = os.path.join(ROOT, "data", "experimento1")
DEFAULT_MODIFICADAS = os.path.join(DIR_EXP, "modificadas.jsonl")
DEFAULT_SEMENTE = 42
CAMPOS_AVALIADOR = ["item_id", "habilidade_codigo", "ano", "enunciado", "alternativas", "gabarito"]
CAMPOS_CHAVE = ["item_id", "id", "id_original", "rotulo", "tipo_erro", "llm_adulterador", "lote", "ajuste_manual"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Monta a base do Experimento 1.")
    parser.add_argument("--semente", type=int, default=DEFAULT_SEMENTE)
    args = parser.parse_args()

    with open(DEFAULT_AMOSTRA, encoding="utf-8-sig") as f:
        autenticas = [{
            "id": f"{r['id']}_aut", "id_original": r["id"], "habilidade_codigo": r["habilidade_codigo"],
            "ano": r["ano"], "enunciado": r["enunciado"], "alternativas": json.loads(r["alternativas"]),
            "gabarito": r["gabarito"], "rotulo": "autentica", "tipo_erro": "",
        } for r in csv.DictReader(f)]
    with open(DEFAULT_MODIFICADAS, encoding="utf-8") as f:
        modificadas = [json.loads(l) for l in f if l.strip()]

    ids_aut = {a["id_original"] for a in autenticas}
    ids_mod = {m["id_original"] for m in modificadas}
    if ids_aut != ids_mod:
        raise SystemExit(f"Base incompleta: {len(ids_aut - ids_mod)} autênticas sem versão modificada aprovada.")

    with open(os.path.join(DIR_EXP, "autenticas.jsonl"), "w", encoding="utf-8") as f:
        for a in autenticas:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    itens = autenticas + modificadas
    random.Random(args.semente).shuffle(itens)
    for n, item in enumerate(itens, start=1):
        item["item_id"] = f"item_{n:03d}"

    with open(os.path.join(DIR_EXP, "base_experimento.jsonl"), "w", encoding="utf-8") as f:
        for item in itens:
            f.write(json.dumps({c: item[c] for c in CAMPOS_AVALIADOR}, ensure_ascii=False) + "\n")
    with open(os.path.join(DIR_EXP, "base_experimento_chave.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CHAVE)
        writer.writeheader()
        writer.writerows({c: item.get(c, "") for c in CAMPOS_CHAVE} for item in itens)

    print(f"{len(autenticas)} autênticas + {len(modificadas)} modificadas = {len(itens)} itens (semente {args.semente})")


if __name__ == "__main__":
    main()
