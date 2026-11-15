"""
Experimento 1 — Fase 2.4: página HTML de revisão manual das adulterações.

Gera data/experimento1/revisao/revisao_adulteracoes.html, um arquivo único com os 140
itens embutidos (original × adulterado com diff, descrição do modelo, avisos do
validador e, se existir, a pré-triagem). As decisões ficam salvas no navegador e são
exportadas pela própria página para revisao_adulteracoes.csv, que alimenta
consolidar_revisao.py.

Cada item leva uma "impressao" (hash do conteúdo adulterado): se um lote for refeito e
a página regenerada, decisões antigas desse item deixam de valer automaticamente.

Uso:
    python scripts/experimento1/gerar_pagina_revisao.py
"""
import os
import re
import csv
import sys
import json
import difflib
import hashlib
import argparse
from typing import Dict, List

sys.path.insert(0, os.path.dirname(__file__))
from prompt_adulteracao import DEFAULT_AMOSTRA, DEFAULT_ATRIBUICAO, ROOT, load_itens_atribuidos  # noqa: E402
from validar_adulteracoes import DEFAULT_MANIFESTO, LETRAS, extrair_itens, validar_item  # noqa: E402

DIR_REVISAO = os.path.join(ROOT, "data", "experimento1", "revisao")
DEFAULT_SAIDA = os.path.join(DIR_REVISAO, "revisao_adulteracoes.html")
DEFAULT_PRETRIAGEM = os.path.join(DIR_REVISAO, "pretriagem.csv")
DEFAULT_MANIFESTO_REENVIO = os.path.join(os.path.dirname(DEFAULT_MANIFESTO), "manifesto_reenvio.csv")

# Moeda (R$, US$, U$) e \$ são texto; $...$ é LaTeX — mesma convenção do extrator de PDFs.
TOKEN_RE = re.compile(r"\n|\||\\\$|\b(?:R|US|U)\$|\$[^$\n]+\$|[^\s|$]+|\$")

CHECKLIST_POR_TIPO = {
    "GABARITO": [
        "Só a letra do gabarito mudou",
        "O distrator escolhido é plausível (erro típico de raciocínio)",
    ],
    "CALCULO": [
        "Com o dado novo, a alternativa do gabarito deixou de ser a correta",
        "O novo valor é plausível no contexto",
        "Há um único defeito, sem pistas no texto",
    ],
    "AMBIGUIDADE": [
        "Há duas ou mais leituras razoáveis",
        "As leituras levam a respostas diferentes",
        "Há um único defeito, sem pistas no texto",
    ],
    "CONTRADICAO": [
        "Os dois trechos não podem ser verdadeiros ao mesmo tempo",
        "A contradição é verificável só lendo o texto",
        "A pergunta final não foi alterada; há um único defeito, sem pistas",
    ],
}


def impressao(item: dict) -> str:
    campos = {c: item.get(c) for c in ("enunciado", "alternativas", "gabarito")}
    return hashlib.sha1(json.dumps(campos, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def ler_respostas(lote: Dict[str, str]) -> Dict[str, dict]:
    caminho = os.path.join(ROOT, lote["resposta"])
    conteudo = open(caminho, encoding="utf-8").read() if os.path.exists(caminho) else ""
    return {str(i.get("id")): i for i in extrair_itens(conteudo)} if conteudo.strip() else {}


def carregar_adulteracoes(manifesto: str = DEFAULT_MANIFESTO, amostra: str = DEFAULT_AMOSTRA,
                          atribuicao: str = DEFAULT_ATRIBUICAO,
                          manifesto_reenvio: str = DEFAULT_MANIFESTO_REENVIO) -> List[dict]:
    """Junta cada item adulterado com a questão original e os dados do lote, na ordem do manifesto.

    Se um item foi reenviado e a resposta do reenvio já foi colada, ela substitui a original.
    """
    originais = load_itens_atribuidos(amostra, atribuicao)
    with open(manifesto, encoding="utf-8") as f:
        lotes = list(csv.DictReader(f))

    reenviados: Dict[str, tuple] = {}
    if os.path.exists(manifesto_reenvio):
        with open(manifesto_reenvio, encoding="utf-8") as f:
            for lote in csv.DictReader(f):
                for item_id, item in ler_respostas(lote).items():
                    if item_id in lote["ids"].split():
                        reenviados[item_id] = (lote, item)

    registros = []
    for lote in lotes:
        recebidos = ler_respostas(lote)
        for item_id in lote["ids"].split():
            lote_item, item = reenviados.get(item_id, (lote, recebidos.get(item_id)))
            registros.append({
                "lote": lote_item, "id": item_id, "original": originais[item_id], "item": item,
            })
    return registros


def diff_tokens(original: str, novo: str) -> List[List[str]]:
    """Diff por token (palavra, fórmula $...$, '|' ou quebra de linha): [[op, token], ...]."""
    a, b = TOKEN_RE.findall(original or ""), TOKEN_RE.findall(novo or "")
    saida: List[List[str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            saida += [["=", t] for t in a[i1:i2]]
            continue
        saida += [["-", t] for t in a[i1:i2]]
        saida += [["+", t] for t in b[j1:j2]]
    return saida


def montar_registro(reg: dict, pretriagem: Dict[str, dict]) -> dict:
    lote, original, item = reg["lote"], reg["original"], reg["item"] or {}
    tipo = lote["tipo_erro"]
    alt_orig = json.loads(original["alternativas"])
    alt_nova = item.get("alternativas") if isinstance(item.get("alternativas"), dict) else {}
    problemas = validar_item(item, original, tipo) if item else [("ERRO", "item ausente na resposta do LLM")]
    return {
        "id": reg["id"],
        "habilidade": original["habilidade_codigo"],
        "ano": original["ano"],
        "tipo": tipo,
        "llm": lote["llm_adulterador"],
        "lote": lote["lote"],
        "impressao": impressao(item) if item else "",
        "enunciado_diff": diff_tokens(original["enunciado"], item.get("enunciado", "")),
        "alternativas": [
            {"letra": l, "diff": diff_tokens(alt_orig.get(l, ""), alt_nova.get(l, "")),
             "mudou": alt_orig.get(l) != alt_nova.get(l)}
            for l in LETRAS
        ],
        "gabarito_original": original["gabarito"],
        "gabarito_novo": item.get("gabarito", ""),
        "descricao": item.get("descricao_modificacao", ""),
        "trecho_original": item.get("trecho_original", ""),
        "trecho_adulterado": item.get("trecho_adulterado", ""),
        "resposta_correta": item.get("resposta_correta_apos_adulteracao", ""),
        "validador": [{"nivel": n, "mensagem": m} for n, m in problemas],
        # a pré-triagem se refere à primeira tentativa; não vale para um item reenviado
        "pretriagem": None if lote["lote"].startswith("reenvio") else pretriagem.get(reg["id"]),
        "checklist": CHECKLIST_POR_TIPO[tipo],
    }


def carregar_pretriagem(caminho: str) -> Dict[str, dict]:
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera a página de revisão manual das adulterações.")
    parser.add_argument("--saida", default=DEFAULT_SAIDA)
    parser.add_argument("--pretriagem", default=DEFAULT_PRETRIAGEM)
    args = parser.parse_args()

    pretriagem = carregar_pretriagem(args.pretriagem)
    registros = [montar_registro(r, pretriagem) for r in carregar_adulteracoes()]
    dados = json.dumps(registros, ensure_ascii=False).replace("</", "<\\/")

    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    template = open(os.path.join(os.path.dirname(__file__), "pagina_revisao.html"), encoding="utf-8").read()
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write(template.replace("/*__DADOS__*/[]", dados))

    n_pre = sum(1 for r in registros if r["pretriagem"])
    print(f"{len(registros)} itens | pré-triagem: {n_pre or 'não encontrada'}")
    print(f"Página: {os.path.relpath(args.saida, ROOT)}")


if __name__ == "__main__":
    main()
