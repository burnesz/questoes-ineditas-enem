"""
Baseline zero-shot de questões para a avaliação do TCC.

Mesmo modelo e mesmo prompt da Fase 2A (regras, habilidade, tipologia, tema e abertura), mas sem os exemplos
recuperados (RAG), sem few-shot, sem PoT e sem validação: o próprio modelo escreve as alternativas e escolhe o
gabarito numa única geração. Só falhas de formato (JSON ilegível ou incompleto) levam a uma nova geração, para que
a comparação com o especialista tenha uma questão em cada par; elas ficam registradas em 'falhas_formato'.
"""
import json
import time
import logging
from typing import Any, Dict, Optional

from app.core.prompts import BASELINE_QUESTAO_JSON_SCHEMA, build_baseline_questao_prompt
from app.db.models.habilidade import HabilidadeEnem
from app.services.llm_client import LLMClient
from app.services.question_validator import (
    extract_json_from_text,
    format_enunciado_with_table,
    sanitize_latex_json_text,
    sanitize_parsed_dict_values,
)

logger = logging.getLogger(__name__)

TEMPERATURA_GERACAO = 0.2  # a mesma temperatura base da Fase 2A
MAX_TOKENS = 1200
MAX_GERACOES_POR_FORMATO = 3


class FormatoBaselineInvalido(ValueError):
    pass


def _ler_questao(bruto: str) -> Dict[str, Any]:
    dados = sanitize_parsed_dict_values(json.loads(sanitize_latex_json_text(extract_json_from_text(bruto)), strict=False))
    if not isinstance(dados, dict):
        raise FormatoBaselineInvalido("a resposta não é um objeto JSON")
    alternativas = dados.get("alternativas") or {}
    gabarito = str(dados.get("gabarito") or "").strip().upper()[:1]
    if not isinstance(alternativas, dict) or sorted(alternativas) != list("ABCDE"):
        raise FormatoBaselineInvalido(f"alternativas incompletas: {sorted(alternativas) if isinstance(alternativas, dict) else alternativas}")
    if gabarito not in alternativas or not str(dados.get("enunciado") or "").strip():
        raise FormatoBaselineInvalido("gabarito ou enunciado ausente")
    enunciado = str(dados["enunciado"]).strip()
    if dados.get("tabela_dados"):
        enunciado = format_enunciado_with_table(enunciado=enunciado, tabela_dados=dados["tabela_dados"])
    return {"enunciado": enunciado, "alternativas": {k: str(v).strip() for k, v in alternativas.items()}, "gabarito": gabarito}


class BaselineQuestaoService:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def gerar_questao(
        self,
        habilidade: HabilidadeEnem,
        tema: Optional[str] = None,
        abertura: Optional[str] = None,
        tipologia: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        prompt = build_baseline_questao_prompt(
            habilidade_codigo=habilidade.codigo,
            habilidade_descricao=habilidade.descricao,
            competencia=habilidade.competencia,
            eixo_tematico=habilidade.eixo_tematico,
            tema=tema,
            abertura=abertura,
            tipologia=tipologia,
        )
        falhas = []
        inicio = time.time()
        for geracao in range(MAX_GERACOES_POR_FORMATO):
            bruto = self.llm_client.generate(
                prompt=prompt,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURA_GERACAO,
                format=BASELINE_QUESTAO_JSON_SCHEMA,
                seed=None if seed is None else seed + geracao,
            )
            try:
                questao = _ler_questao(bruto)
            except (ValueError, json.JSONDecodeError) as e:
                falhas.append(f"{type(e).__name__}: {e}"[:200])
                logger.warning(f"Baseline {habilidade.codigo}: formato inválido ({e}); gerando de novo.")
                continue
            return {**questao, "falhas_formato": falhas, "tempo_s": round(time.time() - inicio, 2)}
        raise FormatoBaselineInvalido(f"{MAX_GERACOES_POR_FORMATO} gerações sem JSON válido: {falhas}")
