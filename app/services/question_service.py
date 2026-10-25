"""
Serviço orquestrador para geração, validação e persistência de questões inéditas do ENEM via RAG e PoT.
"""

import json
import logging
import os
import random
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.prompts import (
    build_enunciado_plan_only_prompt,
    build_solver_only_prompt,
    build_blind_solving_prompt,
    build_equivalencia_gabarito_prompt,
    build_auditoria_criterio_prompt,
    build_mapeamento_alternativa_prompt,
    criterios_auditoria_por_perfil,
    sortear_contexto_criativo,
)
from app.db.models.ciclo_geracao import CicloGeracao
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.db.models.tentativa_geracao import TentativaGeracao
from app.schemas.question import (
    AvaliacaoItemResult,
    BatchPopulationItemResult,
    BatchPopulationSummary,
    HABILIDADES_DESABILITADAS,
    HabilidadeDesabilitadaError,
    MOTIVOS_HABILIDADES_DESABILITADAS,
    PerfilAvaliacao,
    PipelineErrorCode,
    PipelineValidationError,
    POT_PHASE1A_JSON_SCHEMA,
    POT_PHASE1B_SOLVER_JSON_SCHEMA,
    QuestaoAuditoriaSemanticaOutput,
    QuestaoBlindSolvingOutput,
    QuestaoEnunciadoSolverOutput,
    QuestaoEquivalenciaOutput,
    QuestaoMapeamentoAlternativaOutput,
    QuestaoPlanejamentoEnunciadoOutput,
)
from app.services.code_executor import (
    assemble_alternatives_and_gabarito,
    execute_solver_code,
    validate_solver_complexity,
    validate_solver_consistency,
)
from app.services.llm_client import LLMClient
from app.services.question_validator import (
    check_prohibited_terms,
    extract_json_from_text,
    format_enunciado_with_table,
    sanitize_latex_json_text,
    sanitize_parsed_dict_values,
)
from app.services.vectorstore import ChromaVectorStore

logger = logging.getLogger(__name__)

_RETRY_HINTS_BY_CODE: Dict[PipelineErrorCode, str] = {
    PipelineErrorCode.SINTAXE: "Sintaxe estrita: retorne JSON válido com 'planejamento', 'enunciado', 'tabela_dados' (opcional), 'erros_tipicos' (4 itens) e função def resolver().",
    PipelineErrorCode.SEGURANCA: "Código seguro: não utilize imports externos ou funções de sistema; defina apenas cálculos matemáticos dentro de def resolver().",
    PipelineErrorCode.TIMEOUT: "Eficiência no solver: evite laços infinitos ou simulações pesadas; use fórmulas aritméticas diretas dentro de def resolver().",
    PipelineErrorCode.NOME_LIVRE: "declare os valores como variáveis dentro de resolver(); não use variáveis externas",
    PipelineErrorCode.USO_PI: "se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver",
    PipelineErrorCode.DISTRATORES_INSUFICIENTES: "Distratores insuficientes: defina 4 variáveis 'erro_*' dentro de resolver() produzindo pelo menos 3 valores distintos do gabarito.",
    PipelineErrorCode.ERROS_TIPICOS_INVALIDOS: "Erros típicos: liste exatamente 4 erros cognitivos em 'erros_tipicos' e defina 4 variáveis 'erro_*' correspondentes no solver.",
    PipelineErrorCode.NEXO_NUMERICO: "Nexo numérico: use no solver apenas números presentes no enunciado/tabela (para quantidade de itens/linhas, use len([...])).",
    PipelineErrorCode.COLISAO: "Distratores distintos: calcule 4 variáveis de erros típicos que gerem 4 valores numéricos diferentes entre si e da resposta correta.",
    PipelineErrorCode.TABELA_INVALIDA: "Tabela uniforme: em 'tabela_dados', use no máximo 6 linhas e exatamente as mesmas chaves em todas as linhas.",
    PipelineErrorCode.TERMO_PROIBIDO: "Linguagem limpa: nunca cite termos internos como 'solver', 'python', 'código', 'algoritmo', 'distrator' ou 'gabarito' no enunciado.",
    PipelineErrorCode.COMPLEXIDADE: "Nível trivial: exija pelo menos 2 etapas de raciocínio encadeadas; proibido resolver apenas somando ou lendo a tabela.",
    PipelineErrorCode.CASO_DEGENERADO: "Desempate estrito: em questões de comparação ('mais econômica', 'o maior', 'o menor'), garanta que não haja empate entre opções.",
    PipelineErrorCode.NAO_RESPONDIVEL: "Comando numérico inequívoco: a pergunta final deve pedir um número com unidade explícita (nunca pergunte 'qual plano/opção').",
    PipelineErrorCode.PREMISSA_OCULTA: "Premissas e dados completos: declare todas as bases, áreas, pesos ou convenções no enunciado e garanta que a soma da tabela bata com o texto.",
    PipelineErrorCode.DADOS_OCIOSOS: "Dados com função: todo número citado no enunciado ou tabela deve entrar no cálculo (máximo de 1 dado extra contextual).",
    PipelineErrorCode.NAO_EQUIVALENTE: "Alinhamento enunciado-solver: garanta que a fórmula de 'correta' em def resolver() calcule exatamente o que o comando final pede.",
    PipelineErrorCode.AUDITORIA: "Verossimilhança: utilize ordens de grandeza e contextos fisicamente realistas.",
}


def _classify_retry_hint(error: Union[PipelineErrorCode, PipelineValidationError, None]) -> Optional[str]:
    """Mapeia o código de falha para a diretriz concisa de ajuste para a próxima tentativa."""
    if error is None:
        return None
    if isinstance(error, PipelineValidationError):
        code = error.code
    elif isinstance(error, PipelineErrorCode):
        code = error
    else:
        return _RETRY_HINTS_BY_CODE[PipelineErrorCode.SINTAXE]
    return _RETRY_HINTS_BY_CODE.get(code, _RETRY_HINTS_BY_CODE[PipelineErrorCode.SINTAXE])


def _check_blind_solving_flags(
    blind_sol: QuestaoBlindSolvingOutput
) -> Optional[Tuple[str, PipelineErrorCode, str]]:
    """Etapa 4.1: aplica os early exits da resolução cega. Retorna (etapa_falha, código, motivo) ou None se passou."""
    if not getattr(blind_sol, "pergunta_respondivel", True):
        return (
            "4.1_nao_respondivel",
            PipelineErrorCode.NAO_RESPONDIVEL,
            "O resolvedor cego apontou que a pergunta não é respondível com os dados fornecidos.",
        )

    premissas = getattr(blind_sol, "premissas_assumidas", [])
    premissas_reais = [
        p for p in premissas or []
        if isinstance(p, str) and not re.search(r"^(nenhuma|n/a|nenhum|nada|sem premissas?)\b", p.strip(), re.I)
    ]
    if premissas_reais:
        return (
            "4.1_premissa_oculta",
            PipelineErrorCode.PREMISSA_OCULTA,
            f"Premissas implícitas assumidas na resolução: {'; '.join(premissas_reais)}",
        )

    dados_ociosos = getattr(blind_sol, "dados_nao_utilizados", [])
    ociosos_reais = [
        d for d in dados_ociosos or []
        if isinstance(d, str) and not re.search(r"^(nenhum|nenhuma|n/a|nada|todos foram usados)\b", d.strip(), re.I)
    ]
    if len(ociosos_reais) > 1:
        return (
            "4.1_dados_ociosos",
            PipelineErrorCode.DADOS_OCIOSOS,
            f"Dados ociosos em excesso no enunciado/tabela ({len(ociosos_reais)} não utilizados): {'; '.join(ociosos_reais)}",
        )
    return None


def _audit_error_code(audit: QuestaoAuditoriaSemanticaOutput) -> PipelineErrorCode:
    """Etapa 4.3: converte o critério reprovado na auditoria em PipelineErrorCode."""
    if audit.complexidade_insuficiente:
        return PipelineErrorCode.COMPLEXIDADE
    if audit.comando_ambiguo_ou_incompativel or audit.desalinhamento_comando_grandeza:
        return PipelineErrorCode.NAO_RESPONDIVEL
    if audit.deficit_ou_contradicao:
        return PipelineErrorCode.PREMISSA_OCULTA
    return PipelineErrorCode.AUDITORIA


def _parse_float_br(value: Any) -> Optional[float]:
    """Converte número puro (aceita vírgula decimal) em float; retorna None para qualquer outro texto."""
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


class QuestionService:
    """Orquestrador de geração, validação e persistência de questões inéditas."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        vector_store: Optional[ChromaVectorStore] = None,
        queries_path: str = "data/habilidades_queries.json"
    ):
        self.llm_client = llm_client or LLMClient()
        self.vector_store = vector_store or ChromaVectorStore()
        self.queries_path = queries_path
        self._habilidades_queries = self._load_habilidades_queries()

    def _load_habilidades_queries(self) -> Dict[str, Dict[str, Any]]:
        """Carrega metadados e queries de busca das 30 habilidades de Matemática do ENEM."""
        mapping = {}
        if os.path.exists(self.queries_path):
            try:
                with open(self.queries_path, "r", encoding="utf-8") as f:
                    items = json.load(f)
                for item in items:
                    hab_cod = item.get("habilidade_codigo") or item.get("habilidade", "")
                    clean = hab_cod.strip().upper()
                    mapping[clean] = item
                    if clean.startswith("H"):
                        num_part = clean[1:]
                        if num_part.isdigit():
                            alt_key = f"H{int(num_part)}"
                            alt_key_padded = f"H{int(num_part):02d}"
                            mapping[alt_key] = item
                            mapping[alt_key_padded] = item
            except Exception as e:
                logger.warning(f"Erro ao carregar queries semânticas de '{self.queries_path}': {e}")
        return mapping

    def sortear_tipologia(self, habilidade_codigo: str, excluir: Optional[str] = None) -> Optional[str]:
        """Sorteia uma tipologia de problema cadastrada para a habilidade informada."""
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"
        hab_data = self._habilidades_queries.get(clean_hab) or {}
        tipologias = hab_data.get("tipologias") or []
        if not tipologias:
            return None
        opcoes = [t for t in tipologias if t != excluir] or tipologias
        return random.choice(opcoes)

    def retrieve_few_shot_examples(
        self,
        db: Session,
        habilidade_codigo: str,
        k: int = 3
    ) -> List[QuestaoEnem]:
        """Recupera itens históricos diretamente do banco relacional como fallback."""
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"

        return (
            db.query(QuestaoEnem)
            .filter(QuestaoEnem.habilidade_codigo == clean_hab)
            .order_by(func.random())
            .limit(k)
            .all()
        )

    def retrieve_rag_few_shot_examples(
        self,
        habilidade_codigo: str,
        k: int = 2,
        top_candidates: int = 10,
        db: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        """Recupera exemplos históricos mais similares no ChromaDB com fallback relacional."""
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"

        hab_data = self._habilidades_queries.get(clean_hab)
        if hab_data and hab_data.get("query"):
            query_text = hab_data["query"]
        else:
            query_text = f"Questão de matemática do ENEM avaliando a habilidade {clean_hab}."

        fetch_limit = max(top_candidates, k)

        try:
            results = self.vector_store.search(
                query=query_text,
                namespace=settings.CHROMA_COLLECTION_QUESTOES,
                top_k=fetch_limit,
                filter_dict={"habilidade_codigo": clean_hab}
            )

            few_shot_dicts = []
            for r in results:
                meta = r.get("metadata", {})
                item_hab = meta.get("habilidade_codigo")
                if item_hab and item_hab != clean_hab:
                    continue
                enunciado = meta.get("text") or r.get("text", "")
                alternativas = {
                    "A": meta.get("alt_a", ""),
                    "B": meta.get("alt_b", ""),
                    "C": meta.get("alt_c", ""),
                    "D": meta.get("alt_d", ""),
                    "E": meta.get("alt_e", "")
                }
                few_shot_dicts.append({
                    "co_item": meta.get("co_item"),
                    "ano": meta.get("ano", "ENEM"),
                    "habilidade_origem": meta.get("habilidade_codigo"),
                    "enunciado": enunciado,
                    "alternativas": alternativas,
                    "gabarito": meta.get("gabarito", ""),
                    "score": r.get("score", 0.0)
                })

            if few_shot_dicts:
                total_encontrados = len(few_shot_dicts)
                if total_encontrados > k:
                    few_shot_dicts = random.sample(few_shot_dicts, k=k)
                    few_shot_dicts.sort(key=lambda x: x.get("score", 0.0), reverse=True)

                scores_str = ", ".join([f"{x['score']:.3f}" for x in few_shot_dicts])
                logger.info(
                    f"RAG: {len(few_shot_dicts)} exemplos sorteados dentre os Top-{total_encontrados} "
                    f"do ChromaDB para {clean_hab} (scores: [{scores_str}])."
                )
                return few_shot_dicts

        except Exception as e:
            logger.warning(f"Falha na recuperação RAG via ChromaDB para {clean_hab}: {e}. Acionando fallback relacional...")

        if db:
            itens_db = self.retrieve_few_shot_examples(db, clean_hab, k=k)
            return [
                {
                    "ano": item.ano,
                    "enunciado": item.enunciado,
                    "alternativas": item.alternativas,
                    "gabarito": item.gabarito,
                    "score": 1.0
                }
                for item in itens_db
            ]

        return []

    def generate_single_questao_inedita(
        self,
        db: Session,
        habilidade_codigo: str,
        num_few_shot: int = 2,
        max_attempts: int = 5,
        temperature: float = 0.2,
        top_p: float = 0.9,
        tema: Optional[str] = None,
        abertura: Optional[str] = None
    ) -> QuestaoInedita:
        """Gera uma questão inédita validada para a habilidade informada via pipeline PoT."""
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"
        elif clean_hab.isdigit():
            clean_hab = f"H{int(clean_hab):02d}"

        if clean_hab in HABILIDADES_DESABILITADAS:
            raise HabilidadeDesabilitadaError(clean_hab)

        habilidade = db.get(HabilidadeEnem, clean_hab)
        if not habilidade:
            raise ValueError(f"Habilidade '{clean_hab}' não encontrada na Matriz de Referência do ENEM.")

        if not tema and not abertura:
            tema, abertura = sortear_contexto_criativo()

        few_shot_dicts = self.retrieve_rag_few_shot_examples(
            habilidade_codigo=clean_hab,
            k=num_few_shot,
            db=db
        )

        return self._generate_pot_item(
            db=db,
            habilidade=habilidade,
            few_shot_dicts=few_shot_dicts,
            max_attempts=max_attempts,
            temperature=temperature,
            top_p=top_p,
            tema=tema,
            abertura=abertura
        )

    def _generate_pot_item(
        self,
        db: Session,
        habilidade: HabilidadeEnem,
        few_shot_dicts: List[Dict[str, Any]],
        max_attempts: int = 5,
        temperature: float = 0.2,
        top_p: float = 0.9,
        tema: Optional[str] = None,
        abertura: Optional[str] = None
    ) -> QuestaoInedita:
        """Executa o ciclo iterativo de geração, execução do solver e validação em 3 etapas."""
        clean_hab = habilidade.codigo
        if not tema and not abertura:
            tema, abertura = sortear_contexto_criativo()

        enunciados_recentes: List[str] = []
        if db is not None:
            try:
                recentes_rows = (
                    db.query(QuestaoInedita.enunciado)
                    .filter(
                        QuestaoInedita.habilidade_codigo == clean_hab,
                        QuestaoInedita.is_validated == True,  # noqa: E712
                        QuestaoInedita.enunciado.isnot(None),
                    )
                    .order_by(QuestaoInedita.created_at.desc())
                    .limit(3)
                    .all()
                )
                if isinstance(recentes_rows, list):
                    for row in recentes_rows:
                        if isinstance(row, (tuple, list)) and row and isinstance(row[0], str):
                            enunciados_recentes.append(row[0])
                        elif hasattr(row, "enunciado") and isinstance(row.enunciado, str):
                            enunciados_recentes.append(row.enunciado)
            except Exception:
                enunciados_recentes = []

        logger.info(
            f"Gerando questão inédita via PoT para {clean_hab} "
            f"(Tema: '{tema}' | Abertura: '{abertura}' | {len(few_shot_dicts)} exemplos RAG para ancoragem)..."
        )

        ciclo_t0 = time.time()
        ciclo = CicloGeracao(
            id=uuid.uuid4(),
            habilidade_codigo=clean_hab,
            max_attempts=max_attempts,
            total_tentativas=0,
            sucesso=False,
            tempo_total_segundos=0.0,
        )
        if db is not None:
            db.add(ciclo)
            db.flush()

        last_error: Optional[str] = None
        last_error_code: Optional[PipelineErrorCode] = None
        curr_tipologia: Optional[str] = None
        model_name = getattr(self.llm_client, "model_name", settings.LLM_MODEL)

        for attempt in range(1, max_attempts + 1):
            attempt_t0 = time.time()
            retry_hint: Optional[str] = None
            attempt_seed = random.randint(1, 2_000_000_000)
            base_temp = min(temperature, 0.3)
            curr_tipologia = self.sortear_tipologia(clean_hab, excluir=curr_tipologia)

            if attempt > 1:
                curr_tema, curr_abertura = sortear_contexto_criativo()
                curr_few_shot = self.retrieve_rag_few_shot_examples(
                    habilidade_codigo=clean_hab,
                    k=len(few_shot_dicts) or 2,
                    db=db
                )
                curr_temp = round(min(base_temp + 0.05 * (attempt - 1), 0.3), 2)
                retry_hint = _classify_retry_hint(last_error_code)
                logger.info(
                    f"PoT Retry: Tentativa {attempt}/{max_attempts} para {clean_hab} "
                    f"(Novo tema: '{curr_tema}' | Tipologia: '{curr_tipologia}' | Temp: {curr_temp:.2f} | Seed: {attempt_seed} | Código: {last_error_code} | Alerta: '{retry_hint}')..."
                )
            else:
                curr_tema = tema
                curr_abertura = abertura
                curr_few_shot = few_shot_dicts
                curr_temp = round(base_temp, 2)
                logger.info(
                    f"PoT: Tentativa {attempt}/{max_attempts} para {clean_hab} "
                    f"(Tipologia: '{curr_tipologia}' | Temp: {curr_temp:.2f} | Seed: {attempt_seed})..."
                )

            tentativa = TentativaGeracao(
                id=uuid.uuid4(),
                ciclo_id=ciclo.id,
                habilidade_codigo=clean_hab,
                numero_tentativa=attempt,
                modelo=model_name,
                temperatura=curr_temp,
                top_p=top_p,
                seed=attempt_seed,
                tema=curr_tema,
                abertura=curr_abertura,
                tipologia=curr_tipologia,
                retry_hint=retry_hint,
                few_shot_exemplos=curr_few_shot,
                enunciados_recentes=enunciados_recentes,
                duracao_segundos=0.0,
            )
            if db is not None:
                db.add(tentativa)
                db.flush()

            partial_enunciado: Optional[str] = None
            partial_planejamento: Optional[str] = None
            partial_solver: Optional[str] = None
            partial_alternativas: Optional[Dict[str, Any]] = None
            partial_gabarito: Optional[str] = None
            partial_justificativa: Optional[str] = None

            def _persist_attempt_output(
                is_validated: bool,
                etapa_falha: Optional[str] = None,
                codigo_erro: Optional[PipelineErrorCode] = None,
                motivo_falha: Optional[str] = None,
            ) -> QuestaoInedita:
                tentativa.duracao_segundos = round(time.time() - attempt_t0, 2)
                ciclo.total_tentativas = attempt
                ciclo.tempo_total_segundos = round(time.time() - ciclo_t0, 2)
                ciclo.sucesso = is_validated

                scratchpad_val: Optional[str] = None
                if partial_planejamento or partial_solver:
                    header = (
                        f"# Planejamento PoT:\n# {partial_planejamento}\n\n"
                        if partial_planejamento
                        else ""
                    )
                    solver_part = (
                        f"# Solver Python validado via PoT:\n{partial_solver}"
                        if partial_solver
                        else ""
                    )
                    scratchpad_val = f"{header}{solver_part}".strip() or None

                err_code_str = (
                    codigo_erro.value
                    if isinstance(codigo_erro, PipelineErrorCode)
                    else (str(codigo_erro) if codigo_erro else None)
                )
                questao_out = QuestaoInedita(
                    id=uuid.uuid4(),
                    tentativa_id=tentativa.id,
                    ciclo_id=ciclo.id,
                    habilidade_codigo=clean_hab,
                    enunciado=partial_enunciado,
                    alternativas=partial_alternativas,
                    gabarito=partial_gabarito,
                    justificativa=partial_justificativa,
                    thought_scratchpad=scratchpad_val,
                    is_validated=is_validated,
                    etapa_falha=etapa_falha,
                    codigo_erro=err_code_str,
                    motivo_falha=motivo_falha,
                )
                if db is not None:
                    db.add(questao_out)
                    db.commit()
                    db.refresh(questao_out)
                return questao_out

            prompt_1a = build_enunciado_plan_only_prompt(
                habilidade_codigo=habilidade.codigo,
                habilidade_descricao=habilidade.descricao,
                competencia=habilidade.competencia,
                eixo_tematico=habilidade.eixo_tematico,
                exemplos_referencia=curr_few_shot,
                tema=curr_tema,
                abertura=curr_abertura,
                tipologia=curr_tipologia,
                enunciados_recentes=enunciados_recentes,
                alerta_tentativa_anterior=retry_hint
            )
            parsed_1a: Any = None
            try:
                raw_1a = self.llm_client.generate(
                    prompt=prompt_1a,
                    max_tokens=800,
                    temperature=curr_temp,
                    top_p=top_p,
                    format=POT_PHASE1A_JSON_SCHEMA,
                    seed=attempt_seed
                )
                json_1a = sanitize_latex_json_text(extract_json_from_text(raw_1a))
                parsed_1a = sanitize_parsed_dict_values(json.loads(json_1a, strict=False))
                if isinstance(parsed_1a, dict):
                    partial_enunciado = parsed_1a.get("enunciado") if isinstance(parsed_1a.get("enunciado"), str) else None
                    partial_planejamento = parsed_1a.get("planejamento") if isinstance(parsed_1a.get("planejamento"), str) else None
                plan_out = QuestaoPlanejamentoEnunciadoOutput(**parsed_1a)
                partial_enunciado = plan_out.enunciado
                partial_planejamento = plan_out.planejamento
            except ValidationError as e:
                err_locs = {loc_part for err in e.errors() for loc_part in err.get("loc", ())}
                if "tabela_dados" in err_locs:
                    last_error_code = PipelineErrorCode.TABELA_INVALIDA
                elif "erros_tipicos" in err_locs:
                    last_error_code = PipelineErrorCode.ERROS_TIPICOS_INVALIDOS
                else:
                    last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Erro no schema da Fase 2A (planejamento/enunciado): {e.errors()}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Fase 2A: {e}")
                _persist_attempt_output(False, "2a_planejamento", last_error_code, last_error)
                continue
            except Exception as e:
                last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Falha na Fase 2A (planejamento/enunciado): {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Fase 2A: {e}")
                _persist_attempt_output(False, "2a_planejamento", last_error_code, last_error)
                continue

            if isinstance(parsed_1a, dict) and "solver" in parsed_1a and "def resolver" in str(parsed_1a.get("solver", "")):
                solver_code = str(parsed_1a["solver"])
                partial_solver = solver_code
            else:
                prompt_1b = build_solver_only_prompt(
                    enunciado=plan_out.enunciado,
                    tabela_dados=plan_out.tabela_dados,
                    planejamento=plan_out.planejamento,
                    erros_tipicos=plan_out.erros_tipicos,
                    alerta_tentativa_anterior=retry_hint
                )
                solver_temp = 0.0
                try:
                    raw_1b = self.llm_client.generate(
                        prompt=prompt_1b,
                        max_tokens=512,
                        temperature=solver_temp,
                        top_p=top_p,
                        format=POT_PHASE1B_SOLVER_JSON_SCHEMA,
                        seed=attempt_seed
                    )
                    json_1b = sanitize_latex_json_text(extract_json_from_text(raw_1b))
                    parsed_1b = sanitize_parsed_dict_values(json.loads(json_1b, strict=False))
                    solver_code = parsed_1b.get("solver", "") if isinstance(parsed_1b, dict) else ""
                    partial_solver = solver_code or None
                except Exception as e:
                    last_error_code = PipelineErrorCode.SINTAXE
                    last_error = f"Falha na Fase 2B (geração do solver): {e}"
                    logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Fase 2B: {e}")
                    _persist_attempt_output(False, "2b_solver", last_error_code, last_error)
                    continue

            parsed_data = {
                "planejamento": plan_out.planejamento,
                "enunciado": plan_out.enunciado,
                "tabela_dados": plan_out.tabela_dados,
                "erros_tipicos": plan_out.erros_tipicos,
                "solver": solver_code
            }

            try:
                pot_output = QuestaoEnunciadoSolverOutput(**parsed_data)
                if pot_output.tabela_dados:
                    try:
                        pot_output.enunciado = format_enunciado_with_table(
                            enunciado=pot_output.enunciado,
                            tabela_dados=pot_output.tabela_dados
                        )
                    except Exception as e:
                        logger.warning(f"Aviso ao formatar tabela_dados para Markdown: {e}")
                partial_enunciado = pot_output.enunciado
                partial_planejamento = pot_output.planejamento
                partial_solver = pot_output.solver
            except ValidationError as e:
                err_locs = {loc_part for err in e.errors() for loc_part in err.get("loc", ())}
                if "tabela_dados" in err_locs:
                    last_error_code = PipelineErrorCode.TABELA_INVALIDA
                elif "erros_tipicos" in err_locs:
                    last_error_code = PipelineErrorCode.ERROS_TIPICOS_INVALIDOS
                else:
                    last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Erro no schema do solver: {e.errors()}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou no schema Pydantic: {e}")
                _persist_attempt_output(False, "2_schema_solver", last_error_code, last_error)
                continue

            ok_terms, err_terms = check_prohibited_terms(pot_output.enunciado)
            if not ok_terms:
                last_error_code = PipelineErrorCode.TERMO_PROIBIDO
                last_error = err_terms
                logger.warning(f"Tentativa {attempt}/{max_attempts} descartada por termo proibido: {err_terms}")
                _persist_attempt_output(False, "2_termos_proibidos", last_error_code, last_error)
                continue

            try:
                solver_result = execute_solver_code(pot_output.solver, timeout=5)
            except Exception as e:
                if isinstance(e, PipelineValidationError):
                    last_error_code = e.code
                elif isinstance(e, TimeoutError):
                    last_error_code = PipelineErrorCode.TIMEOUT
                else:
                    last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Erro na execução da função resolver(): {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na execução do código: {e}")
                _persist_attempt_output(False, "3_execucao_solver", last_error_code, last_error)
                continue

            try:
                formatted_values = validate_solver_consistency(
                    enunciado=pot_output.enunciado,
                    code=pot_output.solver,
                    result=solver_result,
                    tabela_dados=pot_output.tabela_dados
                )
                validate_solver_complexity(pot_output.solver)
            except Exception as e:
                if isinstance(e, PipelineValidationError):
                    last_error_code = e.code
                else:
                    last_error_code = PipelineErrorCode.NEXO_NUMERICO
                last_error = f"Erro de consistência matemática ou nexo numérico: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na checagem de nexo/complexidade: {e}")
                _persist_attempt_output(False, "3_nexo_complexidade", last_error_code, last_error)
                continue

            alternativas, gabarito = assemble_alternatives_and_gabarito(formatted_values)
            partial_alternativas = alternativas
            partial_gabarito = gabarito

            try:
                blind_sol = self._run_blind_solving(
                    enunciado=pot_output.enunciado,
                    tabela_dados=pot_output.tabela_dados
                )
                partial_justificativa = blind_sol.resolucao_passo_a_passo
            except Exception as e:
                last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Falha na resolução cega da LLM: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na resolução cega: {e}")
                _persist_attempt_output(False, "4.1_resolucao_cega", last_error_code, last_error)
                continue

            falha_cega = _check_blind_solving_flags(blind_sol)
            if falha_cega:
                etapa_cega, last_error_code, last_error = falha_cega
                logger.warning(f"Tentativa {attempt}/{max_attempts} descartada na resolução cega ({etapa_cega}): {last_error}")
                _persist_attempt_output(False, etapa_cega, last_error_code, last_error)
                continue

            try:
                equiv = self._run_equivalence_check(
                    resultado_solver=solver_result["correta"],
                    resultado_obtido=blind_sol.resultado_obtido
                )
            except Exception as e:
                last_error_code = PipelineErrorCode.NAO_EQUIVALENTE
                last_error = f"Falha no confronto de equivalência: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na equivalência: {e}")
                _persist_attempt_output(False, "4.2_equivalencia", last_error_code, last_error)
                continue

            if not equiv.equivalentes:
                last_error_code = PipelineErrorCode.NAO_EQUIVALENTE
                motivo = equiv.explicacao_equivalencia or "Divergência conceitual ou numérica entre o solver e a resolução cega."
                last_error = f"Divergência matemática no confronto: {motivo}"
                logger.warning(
                    f"Tentativa {attempt}/{max_attempts} descartada por divergência: "
                    f"Solver='{solver_result['correta']}' vs LLM='{blind_sol.resultado_obtido}' | Motivo: {motivo}"
                )
                _persist_attempt_output(False, "4.2_equivalencia", last_error_code, last_error)
                continue

            try:
                audit = self._run_semantic_audit(
                    enunciado=pot_output.enunciado,
                    alternativas=alternativas,
                    tabela_dados=pot_output.tabela_dados,
                    letra_gabarito=gabarito,
                    habilidade_codigo=habilidade.codigo,
                    habilidade_descricao=habilidade.descricao
                )
            except Exception as e:
                last_error_code = PipelineErrorCode.AUDITORIA
                last_error = f"Falha na auditoria semântica: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na auditoria semântica: {e}")
                _persist_attempt_output(False, "4.3_auditoria_pedagogica", last_error_code, last_error)
                continue

            if not audit.aprovada:
                last_error_code = _audit_error_code(audit)
                last_error = f"Rejeição semântica: {audit.motivo_rejeicao}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na auditoria semântica: {audit.motivo_rejeicao}")
                _persist_attempt_output(False, "4.3_auditoria_pedagogica", last_error_code, last_error)
                continue

            logger.info(
                f"Item PoT para {clean_hab} gerado e validado com sucesso na tentativa {attempt}! "
                f"Gabarito: {gabarito} ({alternativas[gabarito]})."
            )

            nova_questao = _persist_attempt_output(True, None, None, None)
            return nova_questao

        raise ValueError(
            f"RN-Q01 (PoT): Não foi possível gerar uma questão inédita válida para {clean_hab} após {max_attempts} tentativas. "
            f"Último erro: {last_error}"
        )

    def _run_blind_solving(
        self,
        enunciado: str,
        tabela_dados: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        perfil: PerfilAvaliacao = "gerada"
    ) -> QuestaoBlindSolvingOutput:
        """Etapa 4.1: Resolução cega pelo modelo apenas a partir do enunciado e dados."""
        prompt = build_blind_solving_prompt(
            enunciado=enunciado,
            tabela_dados=tabela_dados,
            perfil=perfil
        )
        raw = self.llm_client.generate(
            prompt=prompt,
            max_tokens=600,
            temperature=temperature,
            top_p=0.9,
            format="json"
        )
        json_str = extract_json_from_text(raw)
        sanitized = sanitize_latex_json_text(json_str)
        parsed = json.loads(sanitized, strict=False)
        parsed = sanitize_parsed_dict_values(parsed)

        if isinstance(parsed, dict):
            if "resolucao_passo_a_passo" not in parsed:
                parsed["resolucao_passo_a_passo"] = parsed.get("resolucao") or parsed.get("justificativa") or "Resolução detalhada."
            if "resultado_obtido" not in parsed:
                parsed["resultado_obtido"] = parsed.get("resultado", parsed.get("correta", ""))

        return QuestaoBlindSolvingOutput(**parsed)

    def _run_equivalence_check(self, resultado_solver: Any, resultado_obtido: Any) -> QuestaoEquivalenciaOutput:
        """Etapa 4.2: Confronto de equivalência matemática entre solver e resolução cega."""
        s_solver = str(resultado_solver).strip()
        s_obtido = str(resultado_obtido).strip()
        if s_solver == s_obtido:
            return QuestaoEquivalenciaOutput(
                equivalentes=True,
                explicacao_equivalencia=f"Equivalência exata confirmada deterministicamente em Python (0ms): '{s_solver}' == '{s_obtido}'."
            )

        try:
            f_solver = float(s_solver.replace(",", "."))
            f_obtido = float(s_obtido.replace(",", "."))
            if abs(f_solver - f_obtido) < 1e-4:
                return QuestaoEquivalenciaOutput(
                    equivalentes=True,
                    explicacao_equivalencia=f"Equivalência numérica confirmada deterministicamente em Python (0ms): {f_solver} == {f_obtido}."
                )
        except (ValueError, TypeError):
            pass

        prompt = build_equivalencia_gabarito_prompt(
            resultado_solver=resultado_solver,
            resultado_obtido=resultado_obtido
        )
        raw = self.llm_client.generate(
            prompt=prompt,
            max_tokens=200,
            temperature=0.0,
            top_p=0.9,
            format="json"
        )
        json_str = extract_json_from_text(raw)
        sanitized = sanitize_latex_json_text(json_str)
        parsed = json.loads(sanitized, strict=False)
        parsed = sanitize_parsed_dict_values(parsed)

        if isinstance(parsed, dict):
            if "equivalentes" not in parsed:
                parsed["equivalentes"] = bool(parsed.get("sao_equivalentes", True))

        return QuestaoEquivalenciaOutput(**parsed)

    def _run_alternative_mapping(
        self,
        enunciado: str,
        resultado_obtido: Any,
        alternativas: Dict[str, str]
    ) -> QuestaoMapeamentoAlternativaOutput:
        """Etapa 4.2 (perfil 'enem'): identifica quais alternativas expressam o resultado da resolução cega."""
        f_obtido = _parse_float_br(resultado_obtido)
        floats_alts = {letra: _parse_float_br(texto) for letra, texto in alternativas.items()}
        if f_obtido is not None and all(v is not None for v in floats_alts.values()):
            letras = sorted(letra for letra, v in floats_alts.items() if abs(v - f_obtido) < 1e-4)
            return QuestaoMapeamentoAlternativaOutput(
                letras_equivalentes=letras,
                explicacao=f"Mapeamento numérico determinístico em Python (0ms): {f_obtido} -> {letras or 'nenhuma'}."
            )

        prompt = build_mapeamento_alternativa_prompt(
            enunciado=enunciado,
            resultado_obtido=resultado_obtido,
            alternativas=alternativas
        )
        raw = self.llm_client.generate(
            prompt=prompt,
            max_tokens=200,
            temperature=0.0,
            top_p=0.9,
            format="json"
        )
        json_str = extract_json_from_text(raw)
        sanitized = sanitize_latex_json_text(json_str)
        parsed = json.loads(sanitized, strict=False)
        parsed = sanitize_parsed_dict_values(parsed)
        return QuestaoMapeamentoAlternativaOutput(**parsed)

    def _run_semantic_audit(
        self,
        enunciado: str,
        alternativas: Dict[str, str],
        tabela_dados: Optional[List[Dict[str, Any]]] = None,
        letra_gabarito: Optional[str] = None,
        habilidade_codigo: Optional[str] = None,
        habilidade_descricao: Optional[str] = None,
        perfil: PerfilAvaliacao = "gerada"
    ) -> QuestaoAuditoriaSemanticaOutput:
        """Etapa 4.3: Auditoria semântica e pedagógica por critérios com interrupção rápida."""
        criterios = criterios_auditoria_por_perfil(perfil)
        flags: Dict[str, Any] = {c: False for c in criterios}
        evidencias: List[str] = []

        for criterio in criterios:
            prompt = build_auditoria_criterio_prompt(
                criterio=criterio,
                enunciado=enunciado,
                alternativas=alternativas,
                tabela_dados=tabela_dados,
                letra_gabarito=letra_gabarito,
                habilidade_codigo=habilidade_codigo,
                habilidade_descricao=habilidade_descricao,
                perfil=perfil
            )
            raw = self.llm_client.generate(
                prompt=prompt,
                max_tokens=160,
                temperature=0.0,
                top_p=0.9,
                format="json"
            )
            json_str = extract_json_from_text(raw)
            sanitized = sanitize_latex_json_text(json_str)
            parsed = json.loads(sanitized, strict=False)
            parsed = sanitize_parsed_dict_values(parsed)

            if isinstance(parsed, dict) and "defeito" not in parsed and "incoerencia_ou_absurdo" in parsed:
                return QuestaoAuditoriaSemanticaOutput(**parsed)

            defeito = bool(parsed.get("defeito", False)) if isinstance(parsed, dict) else False
            evidencia = str(parsed.get("evidencia", "")).strip() if isinstance(parsed, dict) else ""
            flags[criterio] = defeito
            if defeito:
                if evidencia:
                    evidencias.append(f"[{criterio}] {evidencia}")
                break

        flags["analise"] = " | ".join(evidencias) if evidencias else "Item adequado."
        return QuestaoAuditoriaSemanticaOutput(**flags)

    def evaluate_item(
        self,
        enunciado: str,
        alternativas: Dict[str, str],
        gabarito: str,
        habilidade_codigo: Optional[str] = None,
        habilidade_descricao: Optional[str] = None,
        tabela_dados: Optional[List[Dict[str, Any]]] = None,
        perfil: PerfilAvaliacao = "enem"
    ) -> AvaliacaoItemResult:
        """
        Avalia um item pronto (ex.: questão histórica do ENEM) apenas com a Etapa 4, sem geração e sem solver.
        - 4.1: resolução cega com os mesmos early exits da geração.
        - 4.2: perfil 'enem' mapeia a resolução cega para as alternativas e exige exatamente a letra do gabarito;
          perfil 'gerada' confronta a resolução cega com o texto da alternativa do gabarito.
        - 4.3: auditoria pedagógica com os critérios do perfil.
        """
        gabarito = gabarito.strip().upper()
        if habilidade_codigo and not habilidade_descricao:
            hab_info = self._habilidades_queries.get(habilidade_codigo.strip().upper(), {})
            habilidade_descricao = hab_info.get("descricao_original") or hab_info.get("descricao")

        def _falha(etapa: str, codigo: PipelineErrorCode, motivo: str, **extra: Any) -> AvaliacaoItemResult:
            return AvaliacaoItemResult(
                perfil=perfil, aprovada=False, etapa_falha=etapa, codigo_erro=codigo, motivo_falha=motivo, **extra
            )

        try:
            blind_sol = self._run_blind_solving(enunciado=enunciado, tabela_dados=tabela_dados, perfil=perfil)
        except Exception as e:
            return _falha("4.1_resolucao_cega", PipelineErrorCode.SINTAXE, f"Falha na resolução cega da LLM: {e}")

        extra: Dict[str, Any] = {
            "resultado_obtido": blind_sol.resultado_obtido,
            "resolucao_passo_a_passo": blind_sol.resolucao_passo_a_passo,
        }
        falha_cega = _check_blind_solving_flags(blind_sol)
        if falha_cega:
            return _falha(*falha_cega, **extra)

        try:
            if perfil == "enem":
                mapeamento = self._run_alternative_mapping(
                    enunciado=enunciado,
                    resultado_obtido=blind_sol.resultado_obtido,
                    alternativas=alternativas
                )
                letras = mapeamento.letras_equivalentes
                extra["letras_mapeadas"] = letras
                if len(letras) > 1:
                    return _falha(
                        "4.2_equivalencia", PipelineErrorCode.ALTERNATIVAS_AMBIGUAS,
                        f"Mais de uma alternativa expressa o resultado da resolução cega: {letras}. {mapeamento.explicacao or ''}".strip(),
                        **extra
                    )
                if letras != [gabarito]:
                    return _falha(
                        "4.2_equivalencia", PipelineErrorCode.NAO_EQUIVALENTE,
                        f"Resolução cega corresponde a {letras or 'nenhuma alternativa'}, gabarito informado é {gabarito}. "
                        f"{mapeamento.explicacao or ''}".strip(),
                        **extra
                    )
            else:
                equiv = self._run_equivalence_check(
                    resultado_solver=alternativas.get(gabarito, ""),
                    resultado_obtido=blind_sol.resultado_obtido
                )
                if not equiv.equivalentes:
                    return _falha(
                        "4.2_equivalencia", PipelineErrorCode.NAO_EQUIVALENTE,
                        f"Divergência matemática no confronto: {equiv.explicacao_equivalencia or ''}".strip(),
                        **extra
                    )
        except Exception as e:
            return _falha("4.2_equivalencia", PipelineErrorCode.NAO_EQUIVALENTE, f"Falha no confronto de equivalência: {e}", **extra)

        try:
            audit = self._run_semantic_audit(
                enunciado=enunciado,
                alternativas=alternativas,
                tabela_dados=tabela_dados,
                letra_gabarito=gabarito,
                habilidade_codigo=habilidade_codigo,
                habilidade_descricao=habilidade_descricao,
                perfil=perfil
            )
        except Exception as e:
            return _falha("4.3_auditoria_pedagogica", PipelineErrorCode.AUDITORIA, f"Falha na auditoria semântica: {e}", **extra)

        if not audit.aprovada:
            return _falha(
                "4.3_auditoria_pedagogica", _audit_error_code(audit), f"Rejeição semântica: {audit.motivo_rejeicao}", **extra
            )

        return AvaliacaoItemResult(perfil=perfil, aprovada=True, **extra)

    def generate_batch(
        self,
        db: Session,
        habilidades: Optional[List[str]] = None,
        count_per_habilidade: int = 1,
        num_few_shot: int = 2,
        on_progress: Optional[Callable[[str, int, int, bool, Optional[str]], None]] = None
    ) -> BatchPopulationSummary:
        """Gera lote de questões inéditas para as habilidades especificadas ou para todas as ativas (28)."""
        start_time = time.time()

        if not habilidades:
            all_habs = db.query(HabilidadeEnem).order_by(HabilidadeEnem.codigo).all()
            target_codes = [h.codigo for h in all_habs if h.codigo not in HABILIDADES_DESABILITADAS]
        else:
            target_codes = []
            for h in habilidades:
                c = h.strip().upper()
                if c.startswith("H") and c[1:].isdigit():
                    c = f"H{int(c[1:]):02d}"
                elif c.isdigit():
                    c = f"H{int(c):02d}"
                target_codes.append(c)

        results: List[BatchPopulationItemResult] = []
        total_success = 0
        total_failures = 0
        total_operations = len(target_codes) * count_per_habilidade
        current_op = 0
        failed_habilidades = []

        for hab_code in target_codes:
            if hab_code in HABILIDADES_DESABILITADAS:
                logger.warning(
                    f"A habilidade {hab_code} está desabilitada para geração e registrará falha. "
                    f"Motivo: {MOTIVOS_HABILIDADES_DESABILITADAS.get(hab_code, '')}"
                )
            for item_idx in range(1, count_per_habilidade + 1):
                current_op += 1
                op_start = time.time()
                try:
                    questao = self.generate_single_questao_inedita(
                        db=db,
                        habilidade_codigo=hab_code,
                        num_few_shot=num_few_shot,
                        max_attempts=5
                    )
                    elapsed = round(time.time() - op_start, 2)
                    total_success += 1
                    used_attempts = (
                        questao.ciclo.total_tentativas
                        if getattr(questao, "ciclo", None) and questao.ciclo.total_tentativas
                        else 1
                    )
                    result_item = BatchPopulationItemResult(
                        habilidade_codigo=hab_code,
                        questao_id=questao.id,
                        success=True,
                        attempts=used_attempts,
                        elapsed_seconds=elapsed
                    )
                    results.append(result_item)
                    if on_progress:
                        on_progress(hab_code, current_op, total_operations, True, None)

                except Exception as e:
                    elapsed = round(time.time() - op_start, 2)
                    total_failures += 1
                    err_msg = str(e)
                    if hab_code not in failed_habilidades:
                        failed_habilidades.append(hab_code)
                    result_item = BatchPopulationItemResult(
                        habilidade_codigo=hab_code,
                        questao_id=None,
                        success=False,
                        attempts=5,
                        error=err_msg,
                        elapsed_seconds=elapsed
                    )
                    results.append(result_item)
                    if on_progress:
                        on_progress(hab_code, current_op, total_operations, False, err_msg)

        if failed_habilidades:
            logger.warning(f"Resumo do Lote - Habilidades que falharam após todas tentativas: {failed_habilidades}")

        total_elapsed = round(time.time() - start_time, 2)
        return BatchPopulationSummary(
            total_habilidades_processadas=len(target_codes),
            total_sucesso=total_success,
            total_falhas=total_failures,
            tempo_total_segundos=total_elapsed,
            habilidades_com_erro=failed_habilidades,
            itens=results
        )

    def list_questoes_ineditas(
        self,
        db: Session,
        habilidade_codigo: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        only_validated: bool = True,
    ) -> List[QuestaoInedita]:
        """Consulta questões inéditas persistidas com paginação e filtro por habilidade."""
        query = db.query(QuestaoInedita)
        if only_validated:
            query = query.filter(QuestaoInedita.is_validated == True)  # noqa: E712
        if habilidade_codigo:
            query = query.filter(QuestaoInedita.habilidade_codigo == habilidade_codigo.strip().upper())
        return query.order_by(QuestaoInedita.created_at.desc()).offset(skip).limit(limit).all()

    def get_questao_inedita_by_id(
        self,
        db: Session,
        questao_id: uuid.UUID
    ) -> Optional[QuestaoInedita]:
        """Recupera uma questão inédita específica pelo UUID."""
        return db.get(QuestaoInedita, questao_id)
