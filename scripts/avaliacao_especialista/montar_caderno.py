"""
Caderno único de avaliação por especialista: serve ao artigo (validação humana do Experimento 2) e ao TCC
(comparação cega VERA × baseline zero-shot, critério R7 da monografia).

Itens (40, misturados, sem indicar a origem):
    - 10 aprovadas do Qwen2.5 (o gerador escolhido): são as mesmas 10 questões da VERA dos pares do TCC
      (data/avaliacao_especialista/pares_questoes.jsonl), então cada uma serve aos dois estudos;
    - 10 aprovadas do Llama 3.1 e 10 do Qwen3, sorteadas como antes (uma por habilidade antes de repetir);
    - 10 questões da baseline zero-shot (mesmo modelo, mesma habilidade, tema, abertura e tipologia, sem RAG,
      sem few-shot, sem PoT e sem validação), uma para cada questão da VERA dos pares.

Cada item é avaliado sozinho, com a mesma rubrica: os 5 critérios Likert (1 a 5) da monografia e 3 perguntas
Sim/Não (dados coerentes, gabarito correto, usaria na prova). Os dois itens de um mesmo par ficam afastados no
caderno, para o especialista não compará-los lado a lado.

Gera em data/avaliacao_especialista/caderno/:
    caderno_especialista.html   o caderno cego (abre no navegador e imprime)
    ficha_respostas.csv         a planilha em que o especialista registra as notas (abre no Excel)
    chave_caderno.csv           a origem de cada item (NÃO entregar ao especialista)

Uso:
    python scripts/avaliacao_especialista/montar_caderno.py [--por-gerador 10] [--semente 2026] [--distancia 8]
"""
import os
import re
import csv
import json
import html
import random
import sqlite3
import argparse
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
QUESTOES_EXP2 = os.path.join(ROOT, "data", "experimento2", "questoes_geradas.jsonl")
PARES = os.path.join(ROOT, "data", "avaliacao_especialista", "pares_questoes.jsonl")
DIR_SAIDA = os.path.join(ROOT, "data", "avaliacao_especialista", "caderno")
GERADOR_VERA = "qwen2.5:7b-instruct-q4_K_M"

# Critérios Likert: os 5 da monografia para questões inéditas (Seção 4, Critérios de aceitação).
# Os comentários indicam o critério Sim/Não da validação humana do Experimento 2 que cada um substitui.
CRITERIOS_LIKERT = [
    ("plausibilidade", "A situação-problema é plausível: o contexto e os valores são realistas."),  # contexto_realista
    ("comando", "O comando é claro e tem uma única interpretação."),  # enunciado_claro
    ("distratores", "As alternativas erradas correspondem a erros que um estudante cometeria."),  # distratores
    ("dificuldade", "O grau de dificuldade é adequado ao ENEM."),
    ("habilidade", "A questão exige a habilidade indicada da Matriz de Referência."),  # habilidade_alinhada
]
CRITERIOS_SIM_NAO = [
    ("dados_coerentes", "Os dados são suficientes e coerentes entre si (texto, tabela e pergunta)."),
    ("gabarito_correto", "O gabarito indicado está correto."),
    ("usaria_na_prova", "Você usaria esta questão numa prova?"),
]
COLUNAS_FICHA = ["id_item", "avaliador"] + [c for c, _ in CRITERIOS_LIKERT] + [c for c, _ in CRITERIOS_SIM_NAO] \
    + ["observacao"]


def sortear(aprovadas, n, rng):
    """Até n questões, priorizando habilidades diferentes (uma por habilidade antes de repetir)."""
    por_hab = defaultdict(list)
    for q in aprovadas:
        por_hab[q["habilidade_codigo"]].append(q)
    for lista in por_hab.values():
        rng.shuffle(lista)
    habs = sorted(por_hab)
    rng.shuffle(habs)
    escolhidas = []
    while len(escolhidas) < n and any(por_hab.values()):
        for h in habs:
            if por_hab[h] and len(escolhidas) < n:
                escolhidas.append(por_hab[h].pop())
    return escolhidas


def embaralhar_afastando_pares(itens, rng, distancia, tentativas=10000):
    """Embaralha mantendo os dois itens de cada par a pelo menos `distancia` posições um do outro."""
    for _ in range(tentativas):
        ordem = itens[:]
        rng.shuffle(ordem)
        pos = defaultdict(list)
        for i, it in enumerate(ordem):
            if it["par"]:
                pos[it["par"]].append(i)
        if all(abs(a - b) >= distancia for a, b in pos.values()):
            return ordem
    raise RuntimeError(f"Não achei uma ordem com os pares a {distancia} posições; use um --distancia menor.")


def texto_para_html(texto):
    """Converte o enunciado (texto com listas '- ' e tabelas Markdown) em HTML simples."""
    blocos, tabela, lista = [], [], []

    def fechar():
        if tabela:
            linhas = [l for l in tabela if not re.fullmatch(r"\|?\s*:?-{2,}.*", l.strip())]
            celulas = [[html.escape(c.strip()) for c in l.strip().strip("|").split("|")] for l in linhas]
            cab, corpo = celulas[0], celulas[1:]
            blocos.append("<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in cab) + "</tr></thead><tbody>"
                          + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in corpo)
                          + "</tbody></table>")
            tabela.clear()
        if lista:
            blocos.append("<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in lista) + "</ul>")
            lista.clear()

    for linha in texto.split("\n"):
        s = linha.strip()
        if s.startswith("|"):
            if lista:
                fechar()
            tabela.append(s)
        elif s.startswith("- "):
            if tabela:
                fechar()
            lista.append(s[2:])
        else:
            fechar()
            if s:
                blocos.append(f"<p>{html.escape(s)}</p>")
    fechar()
    return "\n".join(blocos)


def montar_itens(por_gerador, rng):
    """Lista de itens {origem, gerador, par, habilidade, questao_id, enunciado, alternativas, gabarito, uso}."""
    with open(QUESTOES_EXP2, encoding="utf-8") as f:
        questoes = [json.loads(l) for l in f if l.strip()]
    with open(PARES, encoding="utf-8") as f:
        pares = [json.loads(l) for l in f if l.strip()]
    aprovadas = defaultdict(list)
    for q in questoes:
        if q["is_validated"]:
            aprovadas[q["modelo"]].append(q)

    itens = []
    for p in pares:
        v, b = p["vera"], p["baseline"]
        itens.append({"origem": "vera", "gerador": GERADOR_VERA, "par": p["id"], "habilidade": p["habilidade"],
                      "questao_id": v["questao_id"], "enunciado": v["enunciado"], "alternativas": v["alternativas"],
                      "gabarito": v["gabarito"], "uso": "exp2+tcc"})
        itens.append({"origem": "baseline", "gerador": GERADOR_VERA, "par": p["id"], "habilidade": p["habilidade"],
                      "questao_id": "", "enunciado": b["enunciado"], "alternativas": b["alternativas"],
                      "gabarito": b["gabarito"], "uso": "tcc"})
    for modelo in sorted(aprovadas):
        if modelo == GERADOR_VERA:
            continue  # o Qwen2.5 entra pelas questões dos pares
        for q in sortear(aprovadas[modelo], por_gerador, rng):
            itens.append({"origem": "vera", "gerador": modelo, "par": "", "habilidade": q["habilidade_codigo"],
                          "questao_id": q["id"], "enunciado": q["enunciado"], "alternativas": q["alternativas"],
                          "gabarito": q["gabarito"], "uso": "exp2"})
    return itens


def html_item(i, it, descricoes):
    alts = "".join(f"<li><b>{l})</b> {html.escape(str(v))}</li>" for l, v in sorted(it["alternativas"].items()))
    escala = "".join(f"<td class='box'>☐ {n}</td>" for n in range(1, 6))
    likert = "".join(f"<tr><td>{n}. {html.escape(t)}</td>{escala}</tr>" for n, (_, t) in enumerate(CRITERIOS_LIKERT, 1))
    base = len(CRITERIOS_LIKERT)
    sim_nao = "".join(f"<tr><td>{base + n}. {html.escape(t)}</td><td class='box'>☐ Sim</td><td class='box'>☐ Não</td></tr>"
                      for n, (_, t) in enumerate(CRITERIOS_SIM_NAO, 1))
    return f"""
<section class="questao">
  <h2>Item {i:02d}</h2>
  <p class="hab"><b>Habilidade {it['habilidade']}:</b> {html.escape(descricoes.get(it['habilidade'], ''))}</p>
  <div class="enunciado">{texto_para_html(it['enunciado'])}</div>
  <ol class="alts">{alts}</ol>
  <p class="gab"><b>Gabarito indicado:</b> {html.escape(str(it['gabarito']))}</p>
  <div class="avaliacao">
  <table class="crit">
    <thead><tr><th>Avalie de 1 (discordo totalmente) a 5 (concordo totalmente)</th>
      <th>1</th><th>2</th><th>3</th><th>4</th><th>5</th></tr></thead>
    <tbody>{likert}</tbody>
  </table>
  <table class="crit"><tbody>{sim_nao}</tbody></table>
  <p class="obs"><b>Observações:</b></p>
  </div>
</section>"""


def main():
    parser = argparse.ArgumentParser(description="Monta o caderno único de avaliação por especialista.")
    parser.add_argument("--por-gerador", type=int, default=10, help="aprovadas do Llama e do Qwen3 (padrão: 10)")
    parser.add_argument("--semente", type=int, default=2026)
    parser.add_argument("--distancia", type=int, default=8, help="distância mínima entre os itens de um par")
    args = parser.parse_args()
    rng = random.Random(args.semente)

    con = sqlite3.connect(os.path.join(ROOT, "questoes_ineditas.db"))
    descricoes = dict(con.execute("SELECT codigo, descricao FROM habilidades_enem").fetchall())
    itens = embaralhar_afastando_pares(montar_itens(args.por_gerador, rng), rng, args.distancia)

    os.makedirs(DIR_SAIDA, exist_ok=True)
    with open(os.path.join(DIR_SAIDA, "chave_caderno.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id_item", "origem", "gerador", "par", "habilidade", "uso", "questao_id"])
        for i, it in enumerate(itens, 1):
            w.writerow([f"I{i:02d}", it["origem"], it["gerador"], it["par"], it["habilidade"], it["uso"],
                        it["questao_id"]])

    with open(os.path.join(DIR_SAIDA, "ficha_respostas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLUNAS_FICHA)
        for i in range(1, len(itens) + 1):
            w.writerow([f"I{i:02d}"] + [""] * (len(COLUNAS_FICHA) - 1))

    lista_likert = "".join(f"<li>{html.escape(t)}</li>" for _, t in CRITERIOS_LIKERT)
    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avaliação de questões de Matemática</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 820px; margin: 24px auto; padding: 0 16px; color: #111; background: #fff; line-height: 1.5; }}
  h1 {{ font-size: 1.5em; }} h2 {{ font-size: 1.15em; border-bottom: 1px solid #999; padding-bottom: 4px; }}
  .instrucoes {{ border: 1px solid #999; padding: 12px 16px; background: #f6f6f6; }}
  .hab {{ font-size: .9em; color: #333; }}
  table {{ border-collapse: collapse; margin: 8px 0; }} th, td {{ border: 1px solid #999; padding: 4px 8px; text-align: left; }}
  .alts {{ list-style: none; padding-left: 0; }} .alts li {{ margin: 2px 0; }}
  .crit {{ width: 100%; font-size: .92em; }} .crit th {{ font-weight: normal; background: #f0f0f0; }}
  .box {{ width: 46px; white-space: nowrap; text-align: center; }}
  .obs {{ min-height: 70px; border-bottom: 1px dotted #999; }}
  .questao {{ margin-bottom: 32px; }}
  @page {{ size: A4; margin: 14mm 14mm 16mm; }}
  @media print {{
    body {{ margin: 0; max-width: none; font-size: 10.5pt; line-height: 1.35; }}
    h2 {{ margin: 0 0 4px; }} p {{ margin: 4px 0; }} .alts {{ margin: 4px 0; }}
    th, td {{ padding: 2px 6px; }} .crit {{ font-size: 9pt; margin: 4px 0; }} .obs {{ min-height: 110px; }}
    .questao {{ page-break-after: always; margin: 0; }} .instrucoes {{ page-break-after: always; }}
    .avaliacao, table {{ break-inside: avoid; }}
  }}
</style></head><body>
<h1>Avaliação de questões de Matemática no estilo ENEM</h1>
<div class="instrucoes">
  <p>Este caderno tem {len(itens)} itens de múltipla escolha no estilo do ENEM, produzidos por diferentes
  processos de elaboração. Cada item vem com a habilidade da Matriz de Referência que ele pretende avaliar e com
  o gabarito indicado.</p>
  <p><b>Para cada item:</b></p>
  <ol>
    <li>Resolva a questão antes de olhar o gabarito indicado.</li>
    <li>Dê uma nota de <b>1</b> (discordo totalmente) a <b>5</b> (concordo totalmente) para cada afirmação:
      <ul>{lista_likert}</ul></li>
    <li>Responda <b>Sim</b> ou <b>Não</b> às três perguntas seguintes (dados coerentes, gabarito correto e uso
      numa prova).</li>
    <li>Se quiser, escreva uma observação, principalmente quando der nota 1 ou 2 ou responder Não.</li>
  </ol>
  <ul>
    <li>Se um critério não puder ser avaliado (por exemplo, porque o enunciado é impossível de resolver), dê nota
      1 ou marque Não e explique nas observações.</li>
  </ul>
  <p>As respostas também podem ser registradas na planilha <code>ficha_respostas.csv</code>: uma linha por item,
  notas de 1 a 5 nas cinco primeiras colunas de critério e <b>S</b> ou <b>N</b> nas três seguintes.</p>
</div>
{''.join(html_item(i, it, descricoes) for i, it in enumerate(itens, 1))}
</body></html>"""
    with open(os.path.join(DIR_SAIDA, "caderno_especialista.html"), "w", encoding="utf-8") as f:
        f.write(pagina)

    contagem = defaultdict(int)
    for it in itens:
        contagem[f"{it['origem']}:{it['gerador'].split(':')[0]}"] += 1
    print(f"{len(itens)} itens: {dict(contagem)}")
    print(f"Habilidades distintas: {len({it['habilidade'] for it in itens})}")
    print(f"Arquivos em {os.path.relpath(DIR_SAIDA, ROOT)}/")


if __name__ == "__main__":
    main()
