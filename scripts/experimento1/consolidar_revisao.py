"""
Experimento 1 — Fase 2.5: consolida a revisão manual em data/experimento1/modificadas.jsonl.

Lê o CSV exportado pela página de revisão (gerar_pagina_revisao.py) e grava apenas os
itens aprovados cuja "impressao" ainda bate com a resposta atual do LLM (um lote refeito
depois da revisão invalida a decisão). Lista pendentes, ajustes e rejeições para que os
itens sejam corrigidos ou reenviados.

Uso:
    python scripts/experimento1/consolidar_revisao.py [--revisao CSV] [--saida JSONL]
"""
import os
import csv
import sys
import json
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from gerar_pagina_revisao import DIR_REVISAO, ROOT, carregar_adulteracoes, impressao  # noqa: E402

DEFAULT_REVISAO = os.path.join(DIR_REVISAO, "revisao_adulteracoes.csv")
DEFAULT_SAIDA = os.path.join(ROOT, "data", "experimento1", "modificadas.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolida a revisão manual das adulterações.")
    parser.add_argument("--revisao", default=DEFAULT_REVISAO)
    parser.add_argument("--saida", default=DEFAULT_SAIDA)
    args = parser.parse_args()

    with open(args.revisao, encoding="utf-8-sig") as f:
        revisao = {row["id"]: row for row in csv.DictReader(f)}

    situacoes: Counter = Counter()
    pendencias = []
    aprovados = []
    for reg in carregar_adulteracoes():
        item, original, lote = reg["item"], reg["original"], reg["lote"]
        linha = revisao.get(reg["id"], {})
        decisao = linha.get("decisao") or "pendente"
        if item is None:
            decisao = "ausente"
        elif decisao != "pendente" and linha.get("impressao") != impressao(item):
            decisao = "desatualizado"
        situacoes[decisao] += 1
        if decisao != "aprovado":
            pendencias.append((decisao, lote["llm_adulterador"], lote["lote"], reg["id"], linha.get("observacao", "")))
            continue
        aprovados.append({
            "id": f"{reg['id']}_mod",
            "id_original": reg["id"],
            "habilidade_codigo": original["habilidade_codigo"],
            "ano": original["ano"],
            "enunciado": item["enunciado"],
            "alternativas": item["alternativas"],
            "gabarito": item["gabarito"],
            "rotulo": "defeituosa",
            "tipo_erro": lote["tipo_erro"],
            "descricao_modificacao": item["descricao_modificacao"],
            "trecho_original": item["trecho_original"],
            "trecho_adulterado": item["trecho_adulterado"],
            "resposta_correta_apos_adulteracao": item["resposta_correta_apos_adulteracao"],
            "llm_adulterador": lote["llm_adulterador"],
            "ajuste_manual": item.get("ajuste_manual", ""),
            "lote": lote["lote"],
            "observacao_revisao": linha.get("observacao", ""),
            "data_revisao": linha.get("data_revisao", ""),
        })

    with open(args.saida, "w", encoding="utf-8") as f:
        for registro in aprovados:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    total = sum(situacoes.values())
    print(f"Itens: {total} | " + " | ".join(f"{k}: {v}" for k, v in sorted(situacoes.items())))
    for decisao, llm, lote, item_id, obs in sorted(pendencias):
        if decisao != "pendente":
            print(f"  [{decisao}] {llm}/{lote} {item_id}: {obs}")
    print(f"{len(aprovados)} aprovados gravados em {os.path.relpath(args.saida, ROOT)}")
    if len(aprovados) < total:
        print("Atenção: a base modificada ainda está incompleta.")


if __name__ == "__main__":
    main()
