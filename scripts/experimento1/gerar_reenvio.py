"""
Experimento 1 — Fase 2.4 (reenvio): lotes para refazer as adulterações reprovadas na revisão.

Lê data/experimento1/revisao/revisao_adulteracoes.csv e reenvia os itens com decisão
"rejeitado" ou "ajustar" ao mesmo LLM que os adulterou. O prompt é o da Fase 2.1 com um
bloco extra: a tentativa anterior de cada item, o motivo da reprovação e regras que
explicitam os critérios usados na revisão.

Saídas:
- data/experimento1/lotes/<llm>/reenvio_NN_<TIPO>.txt          → prompt a colar no chat
- data/experimento1/adulteracoes_brutas/<llm>/reenvio_NN_<TIPO>.json → arquivo vazio para a resposta
- data/experimento1/lotes/manifesto_reenvio.csv                → mesmo formato de manifesto.csv

Depois de colada, a resposta do reenvio substitui a original na página de revisão e na
consolidação (ver carregar_adulteracoes). Arquivos de resposta já preenchidos não são tocados.

Uso:
    python scripts/experimento1/gerar_reenvio.py
"""
import os
import csv
import json
import argparse
from collections import defaultdict
from typing import Dict, List

from prompt_adulteracao import DEFAULT_AMOSTRA, DEFAULT_ATRIBUICAO, ROOT, build_prompt, load_itens_atribuidos
from gerar_lotes import DEFAULT_LOTES_DIR, DEFAULT_RESPOSTAS_DIR, ORDEM_TIPOS, dividir_equilibrado
from gerar_pagina_revisao import DEFAULT_MANIFESTO_REENVIO, DIR_REVISAO, ler_respostas
from validar_adulteracoes import DEFAULT_MANIFESTO

DEFAULT_REVISAO = os.path.join(DIR_REVISAO, "revisao_adulteracoes.csv")
DEFAULT_TAMANHO = 4
DECISOES_REENVIO = ("rejeitado", "ajustar")
MARCADOR_QUESTOES = "\n\nQuestões a adulterar:\n"

REGRAS_REENVIO: Dict[str, str] = {
    "CALCULO": """\
- Altere um único dado numérico. O restante do texto deve continuar coerente com o novo
  valor: não crie contradição com regularidades, totais, exemplos ou frases do texto.
- Não altere a pergunta nem a grandeza pedida.""",
    "AMBIGUIDADE": """\
- A informação retirada ou tornada vaga não pode continuar disponível em outro ponto do
  enunciado, da tabela ou das alternativas.
- Cada leitura razoável deve levar a uma alternativa diferente entre as existentes (uma
  delas pode ser o gabarito). Leituras cujo resultado não aparece nas alternativas não
  servem, porque as próprias alternativas desfazem a ambiguidade.
- Outra opção válida: retirar um dado essencial que não possa ser deduzido de nenhuma
  outra parte, de modo que a pergunta fique sem resposta determinada.
- Não troque a pergunta por outra de leitura única (isso é gabarito errado, não
  ambiguidade), não use construções que pareçam erro de digitação e não dependa de
  conhecimento de outra disciplina.""",
    "CONTRADICAO": """\
- Dois trechos explícitos do texto devem ser logicamente incompatíveis (não podem ser
  ambos verdadeiros), verificável lendo o texto e, no máximo, com uma conta simples.
- Não basta trocar um dado (isso é CALCULO) nem incluir um dado que apenas deixa de se
  aplicar ao caso.""",
}


def limpar_motivo(observacao: str) -> str:
    return observacao.strip() or "Defeito fraco ou de outro tipo."


def bloco_reenvio(ids: List[str], tipo: str, anteriores: Dict[str, dict], motivos: Dict[str, str]) -> str:
    tentativas = []
    for item_id in ids:
        anterior = anteriores.get(item_id, {})
        tentativas.append({
            "id": item_id,
            "descricao_anterior": anterior.get("descricao_modificacao", ""),
            "trecho_original_anterior": anterior.get("trecho_original", ""),
            "trecho_adulterado_anterior": anterior.get("trecho_adulterado", ""),
            "motivo_da_reprovacao": motivos[item_id],
        })
    return (
        "REENVIO: estas questões já foram adulteradas uma vez, e a revisão reprovou o defeito "
        "inserido. Faça uma nova adulteração do mesmo tipo, partindo da questão original abaixo "
        "(não da versão anterior), e evite o problema apontado em cada item. Pode escolher outro "
        "trecho para alterar.\n\nCritérios adicionais da revisão:\n" + REGRAS_REENVIO[tipo]
        + "\n\nTentativas anteriores reprovadas:\n" + json.dumps(tentativas, ensure_ascii=False, indent=2)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os lotes de reenvio das adulterações reprovadas.")
    parser.add_argument("--revisao", default=DEFAULT_REVISAO)
    parser.add_argument("--tamanho", type=int, default=DEFAULT_TAMANHO)
    args = parser.parse_args()

    itens = load_itens_atribuidos(DEFAULT_AMOSTRA, DEFAULT_ATRIBUICAO)
    with open(args.revisao, encoding="utf-8-sig") as f:
        motivos = {r["id"]: limpar_motivo(r["observacao"]) for r in csv.DictReader(f)
                   if r["decisao"] in DECISOES_REENVIO}

    # a tentativa anterior é sempre a dos lotes originais
    anteriores: Dict[str, dict] = {}
    with open(DEFAULT_MANIFESTO, encoding="utf-8") as f:
        for lote in csv.DictReader(f):
            anteriores.update(ler_respostas(lote))

    grupos: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for item_id in sorted(motivos, key=lambda i: (itens[i]["habilidade_codigo"], i)):
        grupos[itens[item_id]["llm_adulterador"]][itens[item_id]["tipo_erro"]].append(item_id)

    manifesto = []
    for llm in sorted(grupos):
        numero = 0
        for tipo in ORDEM_TIPOS:
            if not grupos[llm][tipo]:
                continue
            for ids in dividir_equilibrado(grupos[llm][tipo], args.tamanho):
                numero += 1
                nome = f"reenvio_{numero:02d}_{tipo}"
                prompt_path = os.path.join(DEFAULT_LOTES_DIR, llm, f"{nome}.txt")
                resposta_path = os.path.join(DEFAULT_RESPOSTAS_DIR, llm, f"{nome}.json")

                prompt = build_prompt([itens[i] for i in ids])
                inicio, questoes = prompt.split(MARCADOR_QUESTOES)
                prompt = inicio + "\n\n" + bloco_reenvio(ids, tipo, anteriores, motivos) + MARCADOR_QUESTOES + questoes
                with open(prompt_path, mode="w", encoding="utf-8") as f:
                    f.write(prompt + "\n")
                if not os.path.exists(resposta_path):
                    open(resposta_path, mode="w", encoding="utf-8").close()

                manifesto.append({
                    "lote": nome, "llm_adulterador": llm, "tipo_erro": tipo, "n_itens": len(ids),
                    "ids": " ".join(ids),
                    "prompt": os.path.relpath(prompt_path, ROOT),
                    "resposta": os.path.relpath(resposta_path, ROOT),
                    "modelo_versao": "", "data_execucao": "",
                })

    with open(DEFAULT_MANIFESTO_REENVIO, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifesto[0].keys()))
        writer.writeheader()
        writer.writerows(manifesto)
    for m in manifesto:
        print(f"{m['llm_adulterador']:8} {m['lote']:24} {m['ids']}")
    print(f"{len(manifesto)} lotes, {sum(m['n_itens'] for m in manifesto)} itens → "
          f"{os.path.relpath(DEFAULT_MANIFESTO_REENVIO, ROOT)}")


if __name__ == "__main__":
    main()
