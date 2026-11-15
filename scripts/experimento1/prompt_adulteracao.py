"""
Experimento 1 — Fase 2.1: prompt único de adulteração (igual para GPT, DeepSeek e Gemini).

Cada questão autêntica recebe exatamente um defeito objetivo do tipo definido em
data/experimento1/atribuicao.csv. O prompt pede uma saída JSON por item, com campos
extras (trecho_original, trecho_adulterado, resposta_correta_apos_adulteracao) que
servem apenas à revisão humana e nunca são mostrados ao modelo avaliador.

Uso (pré-visualização):
    python scripts/experimento1/prompt_adulteracao.py --id <ID> [--id <ID> ...]
"""
import os
import csv
import json
import argparse
from typing import Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_AMOSTRA = os.path.join(ROOT, "data", "experimento1", "amostra_140_historicas.csv")
DEFAULT_ATRIBUICAO = os.path.join(ROOT, "data", "experimento1", "atribuicao.csv")

INSTRUCOES_GERAIS = """\
Você é um especialista em elaboração de itens de Matemática do ENEM. Estamos construindo
um conjunto de teste para medir se modelos avaliadores automáticos conseguem detectar
questões defeituosas. Para isso, você vai ADULTERAR questões autênticas do ENEM,
inserindo em cada uma EXATAMENTE UM defeito objetivo do tipo indicado.

Regras obrigatórias:
1. Insira um único defeito, do tipo pedido. Não corrija, melhore nem reescreva o resto.
2. Faça a menor alteração possível: preserve estilo, tamanho, formatação, LaTeX,
   tabelas, unidades e pontuação de todo o texto não envolvido no defeito.
3. O defeito deve ser objetivo e verificável por um professor de Matemática, sem
   depender de opinião.
4. O defeito deve ser discreto: a questão deve continuar parecendo um item real do
   ENEM. Não deixe pistas como "(erro)", "atenção", comentários, negrito ou marcas.
5. Não remova nem acrescente alternativas: devem continuar existindo A, B, C, D e E.
6. Não mencione que a questão foi alterada em nenhum campo exceto
   "descricao_modificacao", "trecho_original", "trecho_adulterado" e
   "resposta_correta_apos_adulteracao".
"""

INSTRUCOES_POR_TIPO: Dict[str, str] = {
    "GABARITO": """\
Tipo de defeito: GABARITO (gabarito incorreto).
- Altere SOMENTE o campo "gabarito" para a letra de uma alternativa incorreta.
- Prefira o distrator mais plausível, que corresponda a um erro típico de raciocínio.
- O "enunciado" e as "alternativas" devem ser devolvidos idênticos ao original.
- Em "trecho_original" e "trecho_adulterado", informe apenas a letra (ex.: "C" e "A").
- Em "resposta_correta_apos_adulteracao", informe a letra correta (a original).""",
    "CALCULO": """\
Tipo de defeito: CALCULO (dado numérico inconsistente).
- Altere UM dado numérico do enunciado (ou da tabela contida nele) de modo que a
  alternativa indicada no gabarito deixe de ser a resposta correta.
- Mantenha as alternativas e o campo "gabarito" idênticos ao original.
- O novo valor deve ser plausível no contexto (sem números absurdos).
- Em "resposta_correta_apos_adulteracao", informe o valor que passa a ser correto e
  diga se ele coincide com alguma das alternativas (e qual) ou com nenhuma.""",
    "AMBIGUIDADE": """\
Tipo de defeito: AMBIGUIDADE (comando ou dados com mais de uma leitura).
- Altere o enunciado para que a pergunta admita duas ou mais interpretações razoáveis
  que levem a respostas diferentes, ou para que falte uma informação essencial
  (por exemplo: remover a unidade pedida, uma restrição, um período de tempo, ou
  tornar ambígua a grandeza solicitada).
- Mantenha as alternativas e o campo "gabarito" idênticos ao original.
- Em "resposta_correta_apos_adulteracao", descreva as leituras possíveis e a resposta
  a que cada uma leva.""",
    "CONTRADICAO": """\
Tipo de defeito: CONTRADICAO (inconsistência interna).
- Altere UM trecho do enunciado (ou da tabela contida nele) para que ele contradiga
  outra informação já presente no próprio texto, de forma que os dados não possam ser
  todos verdadeiros ao mesmo tempo (ex.: "3 horas" em um ponto e "as 4 horas de
  percurso" em outro; parcelas cuja soma difere do total informado; "metade dos 40
  alunos, ou seja, 25"; porcentagens de uma distribuição somando mais de 100%).
- A contradição deve ser verificável apenas lendo o texto, sem conhecimento externo.
- Não altere a pergunta final. Mantenha as alternativas e o campo "gabarito"
  idênticos ao original.
- Em "resposta_correta_apos_adulteracao", cite os dois trechos que se contradizem e
  explique por que não podem ser ambos verdadeiros.""",
}

FORMATO_SAIDA = """\
Responda APENAS com um array JSON dentro de um único bloco de código ```json
(sem texto antes ou depois do bloco), com um objeto por questão, na mesma ordem da entrada. O JSON deve ser válido: dentro
dos valores de texto, escape aspas duplas como \\" e quebras de linha como \\n.
Formato:
[
  {
    "id": "<id da questão, inalterado>",
    "tipo_erro": "<tipo pedido>",
    "enunciado": "<enunciado completo após a adulteração>",
    "alternativas": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."},
    "gabarito": "<letra>",
    "descricao_modificacao": "<1-2 frases explicando o defeito inserido>",
    "trecho_original": "<trecho exato que foi alterado, antes>",
    "trecho_adulterado": "<o mesmo trecho, depois>",
    "resposta_correta_apos_adulteracao": "<conforme as instruções do tipo>"
  }
]"""


def build_prompt(itens: List[Dict[str, str]]) -> str:
    """Monta o prompt para um lote de questões; cada item precisa de 'tipo_erro' definido."""
    tipos = sorted({item["tipo_erro"] for item in itens})
    blocos = [INSTRUCOES_GERAIS]
    blocos += [INSTRUCOES_POR_TIPO[tipo] for tipo in tipos]
    blocos.append(FORMATO_SAIDA)

    entrada = [
        {
            "id": item["id"],
            "tipo_erro": item["tipo_erro"],
            "enunciado": item["enunciado"],
            "alternativas": json.loads(item["alternativas"]),
            "gabarito": item["gabarito"],
        }
        for item in itens
    ]
    blocos.append("Questões a adulterar:\n" + json.dumps(entrada, ensure_ascii=False, indent=2))
    return "\n\n".join(blocos)


def load_itens_atribuidos(amostra_path: str, atribuicao_path: str) -> Dict[str, Dict[str, str]]:
    with open(amostra_path, mode="r", encoding="utf-8-sig") as f:
        amostra = {row["id"]: row for row in csv.DictReader(f)}
    with open(atribuicao_path, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            amostra[row["id"]].update(tipo_erro=row["tipo_erro"], llm_adulterador=row["llm_adulterador"])
    return amostra


def main() -> None:
    parser = argparse.ArgumentParser(description="Pré-visualiza o prompt de adulteração.")
    parser.add_argument("--id", action="append", required=True, dest="ids")
    parser.add_argument("--amostra", default=DEFAULT_AMOSTRA)
    parser.add_argument("--atribuicao", default=DEFAULT_ATRIBUICAO)
    args = parser.parse_args()

    itens = load_itens_atribuidos(args.amostra, args.atribuicao)
    print(build_prompt([itens[item_id] for item_id in args.ids]))


if __name__ == "__main__":
    main()
