"""
Experimento 1 — Fase 2.4: validação estrutural das respostas de adulteração.

Lê cada arquivo de data/experimento1/adulteracoes_brutas/<llm>/<lote>.json listado no
manifesto e confronta com a questão original (amostra + atribuição). Não julga se o
defeito é pedagogicamente bom (isso é revisão humana); verifica apenas se a resposta
obedece às regras objetivas do prompt:

- JSON parseável (aceita bloco ```json e várias partes coladas após "continue");
- mesmos IDs do lote, na mesma ordem, sem faltas nem duplicatas;
- campos obrigatórios presentes e tipo_erro igual ao pedido;
- alternativas exatamente A–E;
- regras por tipo: o que deve ficar idêntico ficou idêntico, o que deve mudar mudou.

Problemas são classificados como ERRO (item inutilizável sem correção) ou AVISO
(merece olhar na revisão humana). Gera data/experimento1/validacao_adulteracoes.csv.

Uso:
    python scripts/experimento1/validar_adulteracoes.py [--llm gpt] [--verbose]
"""
import os
import re
import csv
import sys
import json
import difflib
import argparse
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from prompt_adulteracao import DEFAULT_AMOSTRA, DEFAULT_ATRIBUICAO, ROOT, load_itens_atribuidos  # noqa: E402

DEFAULT_MANIFESTO = os.path.join(ROOT, "data", "experimento1", "lotes", "manifesto.csv")
DEFAULT_SAIDA = os.path.join(ROOT, "data", "experimento1", "validacao_adulteracoes.csv")

LETRAS = ["A", "B", "C", "D", "E"]
CAMPOS_OBRIGATORIOS = [
    "id", "tipo_erro", "enunciado", "alternativas", "gabarito", "descricao_modificacao",
    "trecho_original", "trecho_adulterado", "resposta_correta_apos_adulteracao",
]
PISTAS_PROIBIDAS = re.compile(r"\(erro\)|adulter|\batenção\b|\[\s*defeito|\bmodificad[oa]\b", re.IGNORECASE)
NUMERO_RE = re.compile(
    r"\d+(?:[.,\s]\d+)*|\b(?:zero|um|uma|dois|duas|três|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|"
    r"treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|"
    r"sessenta|setenta|oitenta|noventa|cem|cento|duzentos|trezentos|quinhentos|mil|metade|dobro|triplo|"
    r"terço|quarto|quinto|décimo)\b",
    re.IGNORECASE,
)
# Abaixo desta similaridade (difflib) o enunciado foi reescrito demais para "menor alteração possível".
SIMILARIDADE_MINIMA = 0.85

Problema = Tuple[str, str]  # (nivel, mensagem)


def normalizar_espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def extrair_itens(conteudo: str) -> List[dict]:
    """Extrai a lista de itens de uma resposta colada, com ou sem blocos ```json."""
    blocos = re.findall(r"```(?:json)?\s*\n(.*?)```", conteudo, flags=re.DOTALL)
    partes = blocos or [conteudo]
    itens: List[dict] = []
    for parte in partes:
        dados = json.loads(parte)
        itens.extend(dados if isinstance(dados, list) else [dados])
    return itens


def numeros(texto: str) -> List[str]:
    return [re.sub(r"\s", "", n).lower() for n in NUMERO_RE.findall(texto or "")]


def regioes_alteradas(original: str, novo: str) -> int:
    """Conta trechos alterados por palavra; por caractere, uma troca de palavra vira vários trechos."""
    matcher = difflib.SequenceMatcher(None, original.split(), novo.split(), autojunk=False)
    return sum(1 for op in matcher.get_opcodes() if op[0] != "equal")


def comparar_campo(nome: str, original, novo, problemas: List[Problema]) -> None:
    """Campo que o prompt manda devolver idêntico."""
    if original == novo:
        return
    if isinstance(original, str) and normalizar_espacos(original) == normalizar_espacos(novo):
        problemas.append(("AVISO", f"{nome} difere do original só em espaços/quebras de linha"))
    else:
        problemas.append(("ERRO", f"{nome} foi alterado, mas deveria ficar idêntico ao original"))


def validar_item(item: dict, original: Dict[str, str], tipo: str) -> List[Problema]:
    problemas: List[Problema] = []
    # trecho_adulterado vazio é legítimo quando o defeito consiste em remover um trecho.
    faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in item or (item[c] in (None, "", {}) and c != "trecho_adulterado")]
    if faltando:
        problemas.append(("ERRO", f"campos ausentes ou vazios: {', '.join(faltando)}"))
    if item.get("tipo_erro") != tipo:
        problemas.append(("ERRO", f"tipo_erro={item.get('tipo_erro')!r}, esperado {tipo!r}"))

    alternativas = item.get("alternativas")
    if not isinstance(alternativas, dict) or sorted(alternativas) != LETRAS:
        problemas.append(("ERRO", f"alternativas devem ter exatamente as chaves A–E (veio {alternativas!r:.80})"))
        return problemas
    gabarito = item.get("gabarito")
    if gabarito not in LETRAS:
        problemas.append(("ERRO", f"gabarito inválido: {gabarito!r}"))

    enunciado_orig = original["enunciado"]
    enunciado = item.get("enunciado") or ""
    alternativas_orig = json.loads(original["alternativas"])
    gabarito_orig = original["gabarito"]

    for campo in ("enunciado", "alternativas"):
        valor = enunciado if campo == "enunciado" else " ".join(alternativas.values())
        if PISTAS_PROIBIDAS.search(valor):
            problemas.append(("AVISO", f"{campo} contém possível pista do defeito: {PISTAS_PROIBIDAS.search(valor).group(0)!r}"))

    for letra in LETRAS:
        comparar_campo(f"alternativa {letra}", alternativas_orig[letra], alternativas[letra], problemas)

    if tipo == "GABARITO":
        comparar_campo("enunciado", enunciado_orig, enunciado, problemas)
        if gabarito == gabarito_orig:
            problemas.append(("ERRO", "gabarito não foi trocado"))
        if str(item.get("trecho_original", "")).strip() != gabarito_orig:
            problemas.append(("AVISO", f"trecho_original={item.get('trecho_original')!r}, esperado {gabarito_orig!r}"))
        if str(item.get("trecho_adulterado", "")).strip() != gabarito:
            problemas.append(("AVISO", f"trecho_adulterado={item.get('trecho_adulterado')!r} difere do gabarito {gabarito!r}"))
        if gabarito_orig not in str(item.get("resposta_correta_apos_adulteracao", "")):
            problemas.append(("AVISO", f"resposta_correta_apos_adulteracao não cita a letra original {gabarito_orig!r}"))
        return problemas

    if gabarito != gabarito_orig:
        problemas.append(("ERRO", f"gabarito alterado de {gabarito_orig} para {gabarito}, mas deveria ficar idêntico"))
    if normalizar_espacos(enunciado) == normalizar_espacos(enunciado_orig):
        trecho_orig = normalizar_espacos(str(item.get("trecho_original", "")))
        trecho_novo = normalizar_espacos(str(item.get("trecho_adulterado", "")))
        if trecho_orig != trecho_novo:
            problemas.append(("ERRO", f"enunciado devolvido idêntico ao original, embora a resposta descreva a troca "
                                      f"{trecho_orig[:60]!r} -> {trecho_novo[:60]!r} (alteração não aplicada)"))
        else:
            problemas.append(("ERRO", "enunciado não foi alterado"))
        return problemas

    similaridade = difflib.SequenceMatcher(None, enunciado_orig, enunciado, autojunk=False).ratio()
    if similaridade < SIMILARIDADE_MINIMA:
        problemas.append(("AVISO", f"enunciado muito reescrito (similaridade {similaridade:.2f} < {SIMILARIDADE_MINIMA})"))
    regioes = regioes_alteradas(enunciado_orig, enunciado)
    if regioes > 3:
        problemas.append(("AVISO", f"enunciado alterado em {regioes} pontos distintos (esperado 1 defeito)"))

    trecho_orig = str(item.get("trecho_original", ""))
    trecho_novo = str(item.get("trecho_adulterado", ""))
    if trecho_orig and normalizar_espacos(trecho_orig) not in normalizar_espacos(enunciado_orig):
        problemas.append(("AVISO", "trecho_original não aparece literalmente no enunciado original"))
    if trecho_novo and normalizar_espacos(trecho_novo) not in normalizar_espacos(enunciado):
        problemas.append(("AVISO", "trecho_adulterado não aparece literalmente no enunciado devolvido"))

    if tipo == "CALCULO" and numeros(enunciado) == numeros(enunciado_orig):
        problemas.append(("ERRO", "CALCULO sem alteração de nenhum dado numérico (nem por extenso)"))
    if tipo == "CONTRADICAO":
        # Os enunciados raramente têm quebras de linha; a pergunta é a última frase.
        pergunta_orig = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", normalizar_espacos(enunciado_orig))[-1]
        if not normalizar_espacos(enunciado).endswith(pergunta_orig):
            problemas.append(("AVISO", f"a pergunta final foi alterada: {pergunta_orig[:80]!r}"))
    return problemas


def validar_lote(lote: Dict[str, str], itens_originais: Dict[str, Dict[str, str]]) -> List[dict]:
    caminho = os.path.join(ROOT, lote["resposta"])
    ids_esperados = lote["ids"].split()
    base = {"llm": lote["llm_adulterador"], "lote": lote["lote"]}

    def linha(item_id: str, nivel: str, mensagem: str) -> dict:
        return {**base, "id": item_id, "nivel": nivel, "mensagem": mensagem}

    if not os.path.exists(caminho) or not open(caminho, encoding="utf-8").read().strip():
        return [linha("", "ERRO", "arquivo de resposta ausente ou vazio")]
    try:
        itens = extrair_itens(open(caminho, encoding="utf-8").read())
    except json.JSONDecodeError as exc:
        return [linha("", "ERRO", f"JSON inválido: {exc}")]

    linhas: List[dict] = []
    ids_recebidos = [str(item.get("id", "")) if isinstance(item, dict) else "" for item in itens]
    if ids_recebidos != ids_esperados:
        faltando = [i for i in ids_esperados if i not in ids_recebidos]
        sobrando = [i for i in ids_recebidos if i not in ids_esperados]
        duplicados = sorted({i for i in ids_recebidos if ids_recebidos.count(i) > 1})
        if faltando or sobrando or duplicados:
            linhas.append(linha("", "ERRO", f"IDs divergentes — faltando {faltando}, sobrando {sobrando}, duplicados {duplicados}"))
        else:
            linhas.append(linha("", "AVISO", "IDs fora da ordem do lote"))

    vistos = set()
    for item in itens:
        if not isinstance(item, dict):
            linhas.append(linha("", "ERRO", f"elemento não é objeto JSON: {item!r:.60}"))
            continue
        item_id = str(item.get("id", ""))
        if item_id not in ids_esperados or item_id in vistos:
            continue
        vistos.add(item_id)
        problemas = validar_item(item, itens_originais[item_id], lote["tipo_erro"])
        linhas += [linha(item_id, nivel, mensagem) for nivel, mensagem in problemas]
        if not problemas:
            linhas.append(linha(item_id, "OK", ""))
    return linhas


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida as respostas de adulteração do Experimento 1.")
    parser.add_argument("--llm", help="Valida apenas este LLM (gpt, deepseek, gemini).")
    parser.add_argument("--manifesto", default=DEFAULT_MANIFESTO)
    parser.add_argument("--amostra", default=DEFAULT_AMOSTRA)
    parser.add_argument("--atribuicao", default=DEFAULT_ATRIBUICAO)
    parser.add_argument("--saida", default=DEFAULT_SAIDA)
    parser.add_argument("--verbose", action="store_true", help="Lista também os avisos no terminal.")
    args = parser.parse_args()

    itens_originais = load_itens_atribuidos(args.amostra, args.atribuicao)
    with open(args.manifesto, encoding="utf-8") as f:
        lotes = [l for l in csv.DictReader(f) if not args.llm or l["llm_adulterador"] == args.llm]

    linhas: List[dict] = []
    for lote in lotes:
        linhas += validar_lote(lote, itens_originais)

    with open(args.saida, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["llm", "lote", "id", "nivel", "mensagem"])
        writer.writeheader()
        writer.writerows(linhas)

    total_itens = sum(len(l["ids"].split()) for l in lotes)
    ids_com_erro = {(l["lote"], l["id"]) for l in linhas if l["nivel"] == "ERRO"}
    ids_ok = {(l["lote"], l["id"]) for l in linhas if l["nivel"] == "OK"}
    n_avisos = sum(1 for l in linhas if l["nivel"] == "AVISO")
    print(f"Lotes: {len(lotes)} | itens esperados: {total_itens} | itens sem problemas: {len(ids_ok)}")
    print(f"Erros: {sum(1 for l in linhas if l['nivel'] == 'ERRO')} ({len(ids_com_erro)} itens/lotes) | avisos: {n_avisos}")
    for l in linhas:
        if l["nivel"] == "ERRO" or (args.verbose and l["nivel"] == "AVISO"):
            print(f"  [{l['nivel']}] {l['llm']}/{l['lote']} {l['id'] or '-'}: {l['mensagem']}")
    print(f"Relatório: {os.path.relpath(args.saida, ROOT)}")
    sys.exit(1 if ids_com_erro else 0)


if __name__ == "__main__":
    main()
