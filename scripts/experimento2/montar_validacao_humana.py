"""
Experimento 2 — amostra para a validação humana.

Sorteia N questões APROVADAS por gerador (padrão: 10), espalhadas pelo maior número possível de
habilidades, embaralha tudo e gera, em data/experimento2/validacao_humana/:

    caderno_professores.html   o caderno cego para os professores (abre no navegador e imprime)
    ficha_respostas.csv        a planilha em que cada professor marca as respostas (abre no Excel)
    chave_amostra.csv          qual gerador fez cada questão (NÃO entregar aos professores)

Uso:
    python scripts/experimento2/montar_validacao_humana.py [--por-gerador 10] [--semente 2026]
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
DIR_EXP = os.path.join(ROOT, "data", "experimento2")
DIR_SAIDA = os.path.join(DIR_EXP, "validacao_humana")

CRITERIOS = [
    ("enunciado_claro", "O enunciado é claro e tem uma única interpretação."),
    ("dados_coerentes", "Os dados são suficientes e coerentes entre si (texto, tabela e pergunta)."),
    ("gabarito_correto", "O gabarito indicado está correto."),
    ("distratores_plausiveis", "As alternativas erradas são plausíveis (correspondem a erros que um aluno cometeria)."),
    ("habilidade_alinhada", "A questão exige a habilidade indicada."),
    ("contexto_realista", "O contexto e os valores são realistas."),
]


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


def main():
    parser = argparse.ArgumentParser(description="Monta a amostra cega para a validação humana do Experimento 2.")
    parser.add_argument("--por-gerador", type=int, default=10)
    parser.add_argument("--semente", type=int, default=2026)
    args = parser.parse_args()
    rng = random.Random(args.semente)

    with open(os.path.join(DIR_EXP, "questoes_geradas.jsonl"), encoding="utf-8") as f:
        questoes = [json.loads(l) for l in f if l.strip()]
    aprovadas = defaultdict(list)
    for q in questoes:
        if q["is_validated"]:
            aprovadas[q["modelo"]].append(q)

    con = sqlite3.connect(os.path.join(ROOT, "questoes_ineditas.db"))
    descricoes = dict(con.execute("SELECT codigo, descricao FROM habilidades_enem").fetchall())

    amostra = []
    for modelo in sorted(aprovadas):
        amostra += sortear(aprovadas[modelo], args.por_gerador, rng)
    rng.shuffle(amostra)  # mistura os geradores: o professor não sabe quem fez cada questão

    os.makedirs(DIR_SAIDA, exist_ok=True)
    with open(os.path.join(DIR_SAIDA, "chave_amostra.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id_amostra", "questao_id", "gerador", "habilidade"])
        for i, q in enumerate(amostra, 1):
            w.writerow([f"Q{i:02d}", q["id"], q["modelo"], q["habilidade_codigo"]])

    with open(os.path.join(DIR_SAIDA, "ficha_respostas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id_amostra", "professor"] + [c for c, _ in CRITERIOS] + ["usaria_na_prova", "observacao"])
        for i in range(1, len(amostra) + 1):
            w.writerow([f"Q{i:02d}", ""] + [""] * len(CRITERIOS) + ["", ""])

    itens = []
    for i, q in enumerate(amostra, 1):
        alts = "".join(f"<li><b>{l})</b> {html.escape(str(v))}</li>" for l, v in sorted(q["alternativas"].items()))
        crit = "".join(f"<tr><td>{n}. {html.escape(t)}</td><td class='box'>☐ Sim</td><td class='box'>☐ Não</td></tr>"
                       for n, (_, t) in enumerate(CRITERIOS, 1))
        itens.append(f"""
<section class="questao">
  <h2>Questão Q{i:02d}</h2>
  <p class="hab"><b>Habilidade {q['habilidade_codigo']}:</b> {html.escape(descricoes.get(q['habilidade_codigo'], ''))}</p>
  <div class="enunciado">{texto_para_html(q['enunciado'])}</div>
  <ol class="alts">{alts}</ol>
  <p class="gab"><b>Gabarito indicado:</b> {q['gabarito']}</p>
  <table class="crit"><tbody>{crit}
    <tr><td><b>{len(CRITERIOS) + 1}. Você usaria esta questão numa prova?</b></td><td class='box'>☐ Sim</td><td class='box'>☐ Não</td></tr>
  </tbody></table>
  <p class="obs"><b>Observações:</b></p>
</section>""")

    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Validação de questões de Matemática</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 780px; margin: 24px auto; padding: 0 16px; color: #111; background: #fff; line-height: 1.5; }}
  h1 {{ font-size: 1.5em; }} h2 {{ font-size: 1.15em; border-bottom: 1px solid #999; padding-bottom: 4px; }}
  .instrucoes {{ border: 1px solid #999; padding: 12px 16px; background: #f6f6f6; }}
  .hab {{ font-size: .9em; color: #333; }}
  table {{ border-collapse: collapse; margin: 8px 0; }} th, td {{ border: 1px solid #999; padding: 4px 8px; text-align: left; }}
  .alts {{ list-style: none; padding-left: 0; }} .alts li {{ margin: 2px 0; }}
  .crit {{ width: 100%; font-size: .92em; }} .box {{ width: 70px; white-space: nowrap; }}
  .obs {{ min-height: 70px; border-bottom: 1px dotted #999; }}
  .questao {{ margin-bottom: 32px; }}
  @media print {{ .questao {{ break-inside: avoid; page-break-after: always; }} body {{ margin: 0; }} }}
</style></head><body>
<h1>Validação de questões de Matemática no estilo ENEM</h1>
<div class="instrucoes">
  <p>Este caderno tem {len(amostra)} questões de múltipla escolha elaboradas no estilo do ENEM. Para cada uma, marque
  <b>Sim</b> ou <b>Não</b> em cada critério e, se quiser, escreva uma observação.</p>
  <ul>
    <li>Resolva a questão antes de avaliar o gabarito indicado.</li>
    <li>Avalie cada questão de forma independente, sem consultar outros avaliadores.</li>
    <li>Se um critério não puder ser avaliado, marque <b>Não</b> e explique nas observações.</li>
  </ul>
  <p>As respostas também podem ser registradas na planilha <code>ficha_respostas.csv</code>
  (preencha com <b>S</b> ou <b>N</b>; uma linha por questão).</p>
</div>
{''.join(itens)}
</body></html>"""
    with open(os.path.join(DIR_SAIDA, "caderno_professores.html"), "w", encoding="utf-8") as f:
        f.write(pagina)

    contagem = defaultdict(int)
    for q in amostra:
        contagem[q["modelo"]] += 1
    print(f"{len(amostra)} questões na amostra: {dict(contagem)}")
    print(f"Habilidades distintas: {len({q['habilidade_codigo'] for q in amostra})}")
    print(f"Arquivos em {os.path.relpath(DIR_SAIDA, ROOT)}/")


if __name__ == "__main__":
    main()
