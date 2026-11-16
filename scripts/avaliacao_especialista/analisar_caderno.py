"""
Análise do caderno de avaliação por especialista (montar_caderno.py), depois de preenchido.

Lê a chave e uma ou mais fichas preenchidas (uma por avaliador, ou uma ficha com vários avaliadores) e gera
data/avaliacao_especialista/resultados/tabela_avaliacao_especialista.md com:

    1. Artigo (validação humana do Experimento 2): por gerador, só as questões aprovadas pela VERA:
       % de gabarito correto, % de dados coerentes, % "aprovada pelo especialista" (as duas coisas),
       % "usaria na prova", média e % de notas >= 4 em cada critério Likert.
    2. TCC (R7): os 10 pares VERA × baseline: média de cada condição em cada critério, diferença, teste de
       Wilcoxon pareado e a regra de aceitação da monografia (VERA >= baseline em todos os critérios).
    3. Com 2 ou mais avaliadores: concordância (% de notas iguais e % com diferença de até 1 ponto).

Com mais de um avaliador, a nota de cada item é a média dos avaliadores (e Sim quando a maioria marcou Sim).

Uso:
    python scripts/avaliacao_especialista/analisar_caderno.py ficha_prof1.csv [ficha_prof2.csv ...]
"""
import os
import sys
import csv
import argparse
from statistics import mean
from itertools import combinations
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))
from montar_caderno import CRITERIOS_LIKERT, CRITERIOS_SIM_NAO, DIR_SAIDA  # noqa: E402

LIKERT = [c for c, _ in CRITERIOS_LIKERT]
SIM_NAO = [c for c, _ in CRITERIOS_SIM_NAO]
DIR_RESULTADOS = os.path.join(ROOT, "data", "avaliacao_especialista", "resultados")
NOMES_GERADOR = {"qwen2.5:7b-instruct-q4_K_M": "Qwen2.5 7B", "llama3.1:8b-instruct-q4_K_M": "Llama 3.1 8B",
                 "qwen3:8b-q4_K_M": "Qwen3 8B"}


def ler_csv(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def ler_fichas(caminhos):
    """{id_item: {avaliador: {criterio: valor}}}, validando notas 1..5 e S/N."""
    notas = defaultdict(dict)
    for n_arq, caminho in enumerate(caminhos, 1):
        for linha in ler_csv(caminho):
            item = linha["id_item"].strip()
            avaliador = linha.get("avaliador", "").strip() or f"avaliador{n_arq}"
            registro = {}
            for c in LIKERT:
                v = linha.get(c, "").strip()
                if v:
                    if v not in {"1", "2", "3", "4", "5"}:
                        raise ValueError(f"{caminho}, {item}: nota '{v}' em {c} (use 1 a 5)")
                    registro[c] = int(v)
            for c in SIM_NAO:
                v = linha.get(c, "").strip().upper()
                if v:
                    if v not in {"S", "N", "SIM", "NAO", "NÃO"}:
                        raise ValueError(f"{caminho}, {item}: resposta '{v}' em {c} (use S ou N)")
                    registro[c] = v.startswith("S")
            if registro:
                notas[item][avaliador] = registro
    return notas


def consolidar(notas_item):
    """Média dos avaliadores nas notas Likert; maioria nas respostas Sim/Não (empate conta como Não)."""
    out = {}
    for c in LIKERT:
        vals = [r[c] for r in notas_item.values() if c in r]
        if vals:
            out[c] = mean(vals)
    for c in SIM_NAO:
        vals = [r[c] for r in notas_item.values() if c in r]
        if vals:
            out[c] = sum(vals) > len(vals) / 2
    return out


def pct(valores):
    return f"{100 * sum(valores) / len(valores):.0f}%" if valores else "—"


def media(valores):
    return f"{mean(valores):.2f}".replace(".", ",") if valores else "—"


def wilcoxon_p(x, y):
    diffs = [a - b for a, b in zip(x, y)]
    if len(diffs) < 2 or all(d == 0 for d in diffs):
        return None
    from scipy.stats import wilcoxon
    return float(wilcoxon(x, y, zero_method="zsplit").pvalue)


def secao_artigo(chave, itens):
    linhas = ["## 1. Artigo: validação humana das questões aprovadas no Experimento 2", "",
              "Só as questões aprovadas pela VERA (Etapas 1 a 4, uma tentativa). \"Aprovada pelo especialista\" = "
              "gabarito correto **e** dados coerentes.", "",
              "| Gerador | n | Gabarito correto | Dados coerentes | Aprovada pelo especialista | Usaria na prova | "
              + " | ".join(f"{c} (média / ≥4)" for c in LIKERT) + " |",
              "|---" * (6 + len(LIKERT)) + "|"]
    por_gerador = defaultdict(list)
    for k in chave:
        if k["origem"] == "vera" and k["id_item"] in itens:
            por_gerador[k["gerador"]].append(itens[k["id_item"]])
    for gerador in sorted(por_gerador, key=lambda g: NOMES_GERADOR.get(g, g)):
        its = por_gerador[gerador]
        aprov = [it.get("gabarito_correto", False) and it.get("dados_coerentes", False) for it in its
                 if "gabarito_correto" in it and "dados_coerentes" in it]
        cel = [NOMES_GERADOR.get(gerador, gerador), str(len(its)),
               pct([it["gabarito_correto"] for it in its if "gabarito_correto" in it]),
               pct([it["dados_coerentes"] for it in its if "dados_coerentes" in it]), pct(aprov),
               pct([it["usaria_na_prova"] for it in its if "usaria_na_prova" in it])]
        for c in LIKERT:
            vals = [it[c] for it in its if c in it]
            cel.append(f"{media(vals)} / {pct([v >= 4 for v in vals])}")
        linhas.append("| " + " | ".join(cel) + " |")
    return linhas


def secao_tcc(chave, itens):
    pares = defaultdict(dict)
    for k in chave:
        if k["par"] and k["id_item"] in itens:
            pares[k["par"]][k["origem"]] = itens[k["id_item"]]
    completos = {p: d for p, d in sorted(pares.items()) if "vera" in d and "baseline" in d}
    linhas = ["", "## 2. TCC (R7): VERA × baseline zero-shot", "",
              f"{len(completos)} pares completos (mesmo modelo, mesma habilidade, tema, abertura e tipologia). "
              "Teste de Wilcoxon pareado (bicaudal, `zero_method=zsplit`).", "",
              "| Critério | VERA (média) | Baseline (média) | Diferença | p (Wilcoxon) | VERA ≥ baseline? |",
              "|---|---|---|---|---|---|"]
    aceita = True
    for c, _ in CRITERIOS_LIKERT:
        par_ok = [(d["vera"][c], d["baseline"][c]) for d in completos.values() if c in d["vera"] and c in d["baseline"]]
        if not par_ok:
            linhas.append(f"| {c} | — | — | — | — | — |")
            aceita = False
            continue
        x, y = [a for a, _ in par_ok], [b for _, b in par_ok]
        p = wilcoxon_p(x, y)
        ok = mean(x) >= mean(y)
        aceita &= ok
        linhas.append(f"| {c} | {media(x)} | {media(y)} | {mean(x) - mean(y):+.2f} | "
                      f"{'—' if p is None else f'{p:.3f}'} | {'sim' if ok else '**não**'} |".replace(".", ","))
    for c, _ in CRITERIOS_SIM_NAO:
        x = [d["vera"][c] for d in completos.values() if c in d["vera"]]
        y = [d["baseline"][c] for d in completos.values() if c in d["baseline"]]
        linhas.append(f"| {c} (% Sim) | {pct(x)} | {pct(y)} | — | — | — |")
    linhas += ["", f"**Regra de aceitação da monografia** (VERA ≥ baseline na média de todos os critérios Likert): "
               f"{'atendida' if aceita else 'não atendida'}."]
    return linhas


def secao_concordancia(notas):
    avaliadores = sorted({a for d in notas.values() for a in d})
    if len(avaliadores) < 2:
        return []
    linhas = ["", "## 3. Concordância entre avaliadores", "",
              "| Par de avaliadores | Critério | Itens | Notas iguais | Diferença ≤ 1 |", "|---|---|---|---|---|"]
    for a, b in combinations(avaliadores, 2):
        for c in LIKERT + SIM_NAO:
            vals = [(d[a][c], d[b][c]) for d in notas.values() if a in d and b in d and c in d[a] and c in d[b]]
            if not vals:
                continue
            perto = pct([abs(x - y) <= 1 for x, y in vals]) if c in LIKERT else "—"
            linhas.append(f"| {a} × {b} | {c} | {len(vals)} | {pct([x == y for x, y in vals])} | {perto} |")
    return linhas


def main():
    parser = argparse.ArgumentParser(description="Analisa as fichas preenchidas do caderno do especialista.")
    parser.add_argument("fichas", nargs="+", help="fichas preenchidas (CSV com ';')")
    parser.add_argument("--chave", default=os.path.join(DIR_SAIDA, "chave_caderno.csv"))
    parser.add_argument("--saida", default=os.path.join(DIR_RESULTADOS, "tabela_avaliacao_especialista.md"))
    args = parser.parse_args()

    chave = ler_csv(args.chave)
    notas = ler_fichas(args.fichas)
    desconhecidos = set(notas) - {k["id_item"] for k in chave}
    if desconhecidos:
        raise ValueError(f"Itens que não estão na chave: {sorted(desconhecidos)}")
    itens = {item: consolidar(d) for item, d in notas.items()}

    avaliadores = sorted({a for d in notas.values() for a in d})
    linhas = ["# Avaliação por especialista", "",
              f"{len(itens)} de {len(chave)} itens avaliados; avaliadores: {', '.join(avaliadores)}.", ""]
    linhas += secao_artigo(chave, itens) + secao_tcc(chave, itens) + secao_concordancia(notas)
    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    print("\n".join(linhas))
    print(f"\nGravado em {os.path.relpath(args.saida, ROOT)}")


if __name__ == "__main__":
    main()
