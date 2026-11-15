"""
Experimento 1 — Fase 2.2: lotes de adulteração para colar nas interfaces web.

Agrupa os itens de atribuicao.csv por LLM adulterador e tipo de erro e divide cada
grupo em lotes equilibrados de no máximo --tamanho itens (ex.: 12 → 4+4+4). Cada lote
tem um único tipo de erro, para manter o prompt curto e focado.

Saídas:
- data/experimento1/lotes/<llm>/lote_NN_<TIPO>.txt          → prompt a colar no chat
- data/experimento1/adulteracoes_brutas/<llm>/lote_NN_<TIPO>.json → arquivo vazio onde
  a resposta do chat deve ser colada
- data/experimento1/lotes/manifesto.csv                      → lote, LLM, tipo, ids e
  colunas a preencher manualmente (modelo_versao, data_execucao)
"""
import os
import csv
import math
import logging
import argparse
from collections import defaultdict
from typing import Dict, List

from prompt_adulteracao import DEFAULT_AMOSTRA, DEFAULT_ATRIBUICAO, ROOT, build_prompt, load_itens_atribuidos

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gerar_lotes")

DEFAULT_LOTES_DIR = os.path.join(ROOT, "data", "experimento1", "lotes")
DEFAULT_RESPOSTAS_DIR = os.path.join(ROOT, "data", "experimento1", "adulteracoes_brutas")
DEFAULT_TAMANHO = 5
ORDEM_TIPOS = ["GABARITO", "CALCULO", "AMBIGUIDADE", "CONTRADICAO"]


def dividir_equilibrado(ids: List[str], tamanho_max: int) -> List[List[str]]:
    n_lotes = math.ceil(len(ids) / tamanho_max)
    base, resto = divmod(len(ids), n_lotes)
    lotes, inicio = [], 0
    for i in range(n_lotes):
        fim = inicio + base + (1 if i < resto else 0)
        lotes.append(ids[inicio:fim])
        inicio = fim
    return lotes


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os lotes de adulteração do Experimento 1.")
    parser.add_argument("--amostra", default=DEFAULT_AMOSTRA)
    parser.add_argument("--atribuicao", default=DEFAULT_ATRIBUICAO)
    parser.add_argument("--lotes-dir", default=DEFAULT_LOTES_DIR)
    parser.add_argument("--respostas-dir", default=DEFAULT_RESPOSTAS_DIR)
    parser.add_argument("--tamanho", type=int, default=DEFAULT_TAMANHO)
    args = parser.parse_args()

    itens = load_itens_atribuidos(args.amostra, args.atribuicao)
    grupos: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for item_id in sorted(itens, key=lambda i: (itens[i]["habilidade_codigo"], i)):
        item = itens[item_id]
        grupos[item["llm_adulterador"]][item["tipo_erro"]].append(item_id)

    manifesto = []
    for llm in sorted(grupos):
        os.makedirs(os.path.join(args.lotes_dir, llm), exist_ok=True)
        os.makedirs(os.path.join(args.respostas_dir, llm), exist_ok=True)
        numero = 0
        for tipo in ORDEM_TIPOS:
            for ids in dividir_equilibrado(grupos[llm][tipo], args.tamanho):
                numero += 1
                nome = f"lote_{numero:02d}_{tipo}"
                prompt_path = os.path.join(args.lotes_dir, llm, f"{nome}.txt")
                resposta_path = os.path.join(args.respostas_dir, llm, f"{nome}.json")

                with open(prompt_path, mode="w", encoding="utf-8") as f:
                    f.write(build_prompt([itens[i] for i in ids]) + "\n")
                if not os.path.exists(resposta_path):
                    open(resposta_path, mode="w", encoding="utf-8").close()

                manifesto.append({
                    "lote": nome,
                    "llm_adulterador": llm,
                    "tipo_erro": tipo,
                    "n_itens": len(ids),
                    "ids": " ".join(ids),
                    "prompt": os.path.relpath(prompt_path, ROOT),
                    "resposta": os.path.relpath(resposta_path, ROOT),
                    "modelo_versao": "",
                    "data_execucao": "",
                })
        logger.info(f"{llm}: {numero} lotes")

    manifesto_path = os.path.join(args.lotes_dir, "manifesto.csv")
    with open(manifesto_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifesto[0].keys()))
        writer.writeheader()
        writer.writerows(manifesto)
    logger.info(f"{len(manifesto)} lotes, {sum(m['n_itens'] for m in manifesto)} itens → {manifesto_path}")


if __name__ == "__main__":
    main()
