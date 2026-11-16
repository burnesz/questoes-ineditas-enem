"""Testes da baseline zero-shot de questões: mesmo prompt da Fase 2A, sem RAG, sem few-shot e sem PoT."""
import json
from unittest.mock import MagicMock

import pytest

from app.core.prompts import build_baseline_questao_prompt, build_enunciado_plan_only_prompt
from app.db.models.habilidade import HabilidadeEnem
from app.services.baseline_service import BaselineQuestaoService, FormatoBaselineInvalido
from app.services.llm_client import LLMClient

HAB = HabilidadeEnem(codigo="H03", competencia=1, eixo_tematico="Números",
                     descricao="Resolver situação-problema envolvendo conhecimentos numéricos.")
CRIATIVO = dict(tema="Comércio, varejo ou gestão de estoque", abertura="Inicie com uma situação de compra",
                tipologia="Proporção direta com conversão de unidades")
QUESTAO = {"enunciado": "Uma loja vende 3 cadernos por R$ 12. Quanto custam, em reais, 5 cadernos?",
           "alternativas": {"A": "15", "B": "18", "C": "20", "D": "24", "E": "36"}, "gabarito": "C"}


def _prompts():
    kw = dict(habilidade_codigo=HAB.codigo, habilidade_descricao=HAB.descricao, competencia=HAB.competencia,
              eixo_tematico=HAB.eixo_tematico, **CRIATIVO)
    vera = build_enunciado_plan_only_prompt(exemplos_referencia=[{"ano": 2019, "enunciado": "QUESTAO HISTORICA X",
                                                                  "gabarito": "A", "alternativas": {"A": "1"}}], **kw)
    return vera, build_baseline_questao_prompt(**kw)


def test_prompt_da_baseline_nao_tem_rag_nem_few_shot_nem_solver():
    vera, base = _prompts()
    assert "QUESTAO HISTORICA X" in vera and "QUESTAO HISTORICA X" not in base
    assert "EXEMPLO DE FORMATO" not in base
    assert "def resolver" not in base and '"solver":' not in base and "erro_" not in base
    assert '"alternativas"' in base and '"gabarito"' in base


def test_prompt_da_baseline_mantem_as_regras_e_a_especificacao_da_vera():
    vera, base = _prompts()
    for trecho in ["1. A PERGUNTA FINAL SEMPRE PEDE UM NÚMERO.", "7. DISTRATORES = ERROS TÍPICOS DE ALUNOS",
                   "11. INTEGRIDADE FACTUAL", f"Descrição Oficial do INEP: {HAB.descricao}",
                   f"Tipologia matemática obrigatória para esta questão: {CRIATIVO['tipologia']}",
                   f"Contexto temático sugerido: {CRIATIVO['tema']}"]:
        assert trecho in vera and trecho in base


def test_servico_da_baseline_le_a_questao_numa_unica_geracao():
    llm = MagicMock(spec=LLMClient)
    llm.generate.return_value = json.dumps(QUESTAO)
    q = BaselineQuestaoService(llm_client=llm).gerar_questao(HAB, seed=7, **CRIATIVO)
    assert llm.generate.call_count == 1
    assert llm.generate.call_args.kwargs["temperature"] == 0.2 and llm.generate.call_args.kwargs["seed"] == 7
    assert q["gabarito"] == "C" and q["alternativas"]["C"] == "20" and q["falhas_formato"] == []


def test_servico_da_baseline_so_gera_de_novo_por_falha_de_formato():
    llm = MagicMock(spec=LLMClient)
    llm.generate.side_effect = ['{"enunciado": "x", "alternativas": {"A": "1"}, "gabarito": "A"}', json.dumps(QUESTAO)]
    q = BaselineQuestaoService(llm_client=llm).gerar_questao(HAB, **CRIATIVO)
    assert llm.generate.call_count == 2 and len(q["falhas_formato"]) == 1

    llm.generate.side_effect = ["não é json"] * 3
    with pytest.raises(FormatoBaselineInvalido):
        BaselineQuestaoService(llm_client=llm).gerar_questao(HAB, **CRIATIVO)
