"""
Serviço de geração e gerenciamento de Questões Inéditas de Matemática para o ENEM.
Implementa o fluxo RAG de 4 etapas previsto na Seção 8 do pré-projeto / AGENTS.md:
1. Entrada: Habilidade-alvo da Matriz de Referência do ENEM.
2. Retrieval RAG: Resgate semântico dos Top-3 itens históricos no Pinecone (namespace questoes_enem)
   ancorado nas queries otimizadas pelo Claude.
3. Geração: Prompt estruturado com CoT, three-shot e formato JSON estrito no LLM local (Ollama).
4. Validação Estrutural Automática: Unicidade das alternativas, formato e gabarito (RN-Q01, RN-Q02).
"""

import os
import re
import json
import time
import logging
import uuid
import random
from typing import List, Dict, Any, Optional, Callable, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.services.llm_client import LLMClient
from app.services.vectorstore import ChromaVectorStore
from app.services.question_validator import (
    extract_json_from_text,
    sanitize_latex_json_text,
    sanitize_parsed_dict_values,
    format_enunciado_with_table,
    check_prohibited_terms,
    check_table_duplication
)
from app.services.code_executor import (
    execute_solver_code,
    validate_solver_complexity,
    validate_solver_consistency,
    assemble_alternatives_and_gabarito
)
from app.core.prompts import (
    AUDITORIA_CRITERIOS_B3,
    build_enunciado_solver_prompt,
    build_enunciado_plan_only_prompt,
    build_solver_only_prompt,
    build_blind_solving_prompt,
    build_equivalencia_gabarito_prompt,
    build_auditoria_semantica_prompt,
    build_auditoria_criterio_prompt,
    sortear_contexto_criativo,
    TEMAS_COTIDIANO,
    FORMAS_ABERTURA
)
from app.schemas.question import (
    PipelineErrorCode,
    PipelineValidationError,
    QuestaoEnunciadoSolverOutput,
    QuestaoPlanejamentoEnunciadoOutput,
    QuestaoBlindSolvingOutput,
    QuestaoEquivalenciaOutput,
    QuestaoAuditoriaSemanticaOutput,
    BatchPopulationSummary,
    BatchPopulationItemResult,
    POT_PHASE1_JSON_SCHEMA,
    POT_PHASE1A_JSON_SCHEMA,
    POT_PHASE1B_SOLVER_JSON_SCHEMA
)
from pydantic import ValidationError

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
    PipelineErrorCode.INCONSISTENCIA_CEGA: "Clareza na resolução: redija enunciado e comando inequívocos para que o problema admita uma única interpretação e resultado.",
    PipelineErrorCode.NAO_EQUIVALENTE: "Alinhamento enunciado-solver: garanta que a fórmula de 'correta' em def resolver() calcule exatamente o que o comando final pede.",
    PipelineErrorCode.AUDITORIA: "Verossimilhança: utilize ordens de grandeza e contextos fisicamente realistas.",
}


def _classify_retry_hint(error: Union[PipelineErrorCode, PipelineValidationError, None]) -> Optional[str]:
    """
    Mapeia diretamente o código tipificado de falha (PipelineErrorCode) para uma diretriz curta
    de 1 linha no Stateless Retry, sem busca por substring (A7).
    """
    if error is None:
        return None
    if isinstance(error, PipelineValidationError):
        code = error.code
    elif isinstance(error, PipelineErrorCode):
        code = error
    else:
        return _RETRY_HINTS_BY_CODE[PipelineErrorCode.SINTAXE]
    return _RETRY_HINTS_BY_CODE.get(code, _RETRY_HINTS_BY_CODE[PipelineErrorCode.SINTAXE])


class QuestionService:
    """
    Serviço orquestrador para geração, validação e persistência de itens inéditos via RAG.
    """

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
        """
        Carrega as queries semânticas expandidas das 30 habilidades do ENEM geradas pelo Claude.
        """
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
        """
        Sorteia uma tipologia matemática específica para a habilidade a partir de habilidades_queries.json (B1).
        """
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
        """
        Recupera determinística ou aleatoriamente itens reais do acervo relacional (questoes_enem)
        da mesma habilidade oficial para servirem de fallback.
        """
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"

        exemplos = (
            db.query(QuestaoEnem)
            .filter(QuestaoEnem.habilidade_codigo == clean_hab)
            .order_by(func.random())
            .limit(k)
            .all()
        )
        return exemplos

    def retrieve_rag_few_shot_examples(
        self,
        habilidade_codigo: str,
        k: int = 2,
        top_candidates: int = 10,
        db: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        """
        Recupera os Top-candidates (padrão 10) itens históricos do ENEM mais similares
        semanticamente no Pinecone (namespace 'questoes_enem') e sorteia k exemplos (padrão 2)
        para compor o contexto few-shot, maximizando a diversidade e relevância.
        """
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

        # Fallback relacional no SQLite/PostgreSQL caso ChromaDB falhe ou não retorne resultados
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
        """
        Executa o pipeline RAG de geração de uma questão inédita via Program-Aided Generation (PoT):
        1. Validação da habilidade na Matriz oficial do ENEM.
        2. Retrieval RAG semântico dos Top-k exemplos no namespace 'questoes_enem' do Pinecone.
        3. Geração via Program-Aided Generation (PoT):
           - Fase 1: LLM gera planejamento, situação-problema e def resolver() em Python.
           - Execução isolada em subprocess com timeout e verificação de AST de segurança.
           - Validação de nexo numérico (groundedness) e unicidade estrita das 5 alternativas.
           - Embaralhamento programático das alternativas e definição determinística do gabarito.
           - Validação Cega em 3 Etapas (Resolução Cega + Equivalência + Auditoria Semântica).
        4. Persistência na tabela questoes_ineditas no PostgreSQL.
        """
        clean_hab = habilidade_codigo.strip().upper()
        if clean_hab.startswith("H") and clean_hab[1:].isdigit():
            clean_hab = f"H{int(clean_hab[1:]):02d}"

        # 1. Valida se a habilidade existe na Matriz oficial
        habilidade = db.get(HabilidadeEnem, clean_hab)
        if not habilidade:
            raise ValueError(f"Habilidade '{clean_hab}' não encontrada na Matriz de Referência do ENEM.")

        # 2. Sorteia contexto criativo caso não tenha sido fixado
        if not tema and not abertura:
            tema, abertura = sortear_contexto_criativo()

        # 3. Retrieval RAG semântico no Pinecone (Top-k exemplos mais similares)
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
        """
        Geração Program-Aided (PoT) com execução de código, checagem de nexo numérico
        e montagem algorítmica de alternativas/gabarito.
        """
        clean_hab = habilidade.codigo
        if not tema and not abertura:
            tema, abertura = sortear_contexto_criativo()

        # Recupera até 3 enunciados recentes aprovados para a mesma habilidade a fim de evitar repetição temática
        enunciados_recentes: List[str] = []
        if db is not None:
            try:
                recentes_rows = (
                    db.query(QuestaoInedita.enunciado)
                    .filter(QuestaoInedita.habilidade_codigo == clean_hab)
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

        last_error: Optional[str] = None
        last_error_code: Optional[PipelineErrorCode] = None
        enunciado_anterior: Optional[str] = None
        solver_anterior: Optional[str] = None
        curr_tipologia: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            # Se for retry após falha estrutural, aplica amostragem independente (Stateless Retry)
            # passando apenas uma diretriz curta da categoria do erro anterior (sem o rascunho/código)
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
                    f"PoT Stateless Retry: Tentativa limpa {attempt}/{max_attempts} para {clean_hab} "
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

            # Chamada 1a: Planejamento, Enunciado, Tabela e 4 Erros Típicos
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
                plan_out = QuestaoPlanejamentoEnunciadoOutput(**parsed_1a)
            except ValidationError as e:
                err_locs = {loc_part for err in e.errors() for loc_part in err.get("loc", ())}
                if "tabela_dados" in err_locs:
                    last_error_code = PipelineErrorCode.TABELA_INVALIDA
                elif "erros_tipicos" in err_locs:
                    last_error_code = PipelineErrorCode.ERROS_TIPICOS_INVALIDOS
                else:
                    last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Erro no schema da Etapa 1a (planejamento/enunciado): {e.errors()}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Etapa 1a: {e}")
                continue
            except Exception as e:
                last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Falha na Etapa 1a (planejamento/enunciado): {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Etapa 1a: {e}")
                continue

            # Chamada 1b: Geração estrita do solver em Python condicionado a 1a (temperatura baixa)
            # Se raw_1a já continha solver (compatibilidade retroativa com stubs de teste de payload único), aproveita diretamente
            if isinstance(parsed_1a, dict) and "solver" in parsed_1a and "def resolver" in str(parsed_1a.get("solver", "")):
                solver_code = str(parsed_1a["solver"])
            else:
                prompt_1b = build_solver_only_prompt(
                    enunciado=plan_out.enunciado,
                    tabela_dados=plan_out.tabela_dados,
                    planejamento=plan_out.planejamento,
                    erros_tipicos=plan_out.erros_tipicos,
                    alerta_tentativa_anterior=retry_hint
                )
                solver_temp = round(min(curr_temp, 0.1), 2)
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
                except Exception as e:
                    last_error_code = PipelineErrorCode.SINTAXE
                    last_error = f"Falha na Etapa 1b (geração do solver): {e}"
                    logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na Etapa 1b: {e}")
                    continue

            parsed_data = {
                "planejamento": plan_out.planejamento,
                "enunciado": plan_out.enunciado,
                "tabela_dados": plan_out.tabela_dados,
                "erros_tipicos": plan_out.erros_tipicos,
                "solver": solver_code
            }



            # Validação do Schema Pydantic da Fase 1 (exige solver em Python)
            try:
                pot_output = QuestaoEnunciadoSolverOutput(**parsed_data)
                
                # Conversão e higienização da tabela nativa para Markdown (se existir)
                if pot_output.tabela_dados:
                    try:
                        pot_output.enunciado = format_enunciado_with_table(
                            enunciado=pot_output.enunciado,
                            tabela_dados=pot_output.tabela_dados
                        )
                    except Exception as e:
                        logger.warning(f"Aviso ao formatar tabela_dados para Markdown: {e}")
                
                enunciado_anterior = pot_output.enunciado
                solver_anterior = pot_output.solver
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
                continue

            # --- VALIDAÇÕES DETERMINÍSTICAS EM PYTHON (0ms) ---
            # 1. Vazamento de termos técnicos de bastidor ('solver', 'python', 'código', etc.)
            ok_terms, err_terms = check_prohibited_terms(pot_output.enunciado)
            if not ok_terms:
                last_error_code = PipelineErrorCode.TERMO_PROIBIDO
                last_error = err_terms
                logger.warning(f"Tentativa {attempt}/{max_attempts} descartada por termo proibido: {err_terms}")
                continue

            # --- EXECUÇÃO DO SOLVER EM SUBPROCESS ISOLADO ---
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
                continue

            # --- CHECAGEM DE CONSISTÊNCIA E NEXO NUMÉRICO (GROUNDEDNESS) ---
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
                continue

            # --- MONTAGEM ALGORÍTMICA DE ALTERNATIVAS E GABARITO ---
            alternativas, gabarito = assemble_alternatives_and_gabarito(formatted_values)

            # --- VALIDAÇÃO ETAPA 1: RESOLUÇÃO CEGA PURA (Zero Alternativas) ---
            try:
                blind_sol = self._run_blind_solving(
                    enunciado=pot_output.enunciado,
                    tabela_dados=pot_output.tabela_dados
                )
            except Exception as e:
                last_error_code = PipelineErrorCode.SINTAXE
                last_error = f"Falha na resolução cega da LLM: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na resolução cega: {e}")
                continue

            # Validação Etapa 1b: Auto-relato de Premissas, Pergunta Respondível e Dados Ociosos (Early Exit)
            if not getattr(blind_sol, "pergunta_respondivel", True):
                last_error_code = PipelineErrorCode.NAO_RESPONDIVEL
                last_error = "O resolvedor cego apontou que a pergunta não é respondível numericamente com os dados fornecidos."
                logger.warning(f"Tentativa {attempt}/{max_attempts} descartada (pergunta não respondível): {last_error}")
                continue

            premissas = getattr(blind_sol, "premissas_assumidas", [])
            if premissas:
                premissas_reais = [
                    p for p in premissas
                    if isinstance(p, str) and not re.search(r"^(nenhuma|n/a|nenhum|nada|sem premissas?)\b", p.strip(), re.I)
                ]
                if premissas_reais:
                    last_error_code = PipelineErrorCode.PREMISSA_OCULTA
                    last_error = f"Premissas implícitas assumidas na resolução: {'; '.join(premissas_reais)}"
                    logger.warning(f"Tentativa {attempt}/{max_attempts} descartada por premissa implícita (Early Exit): {last_error}")
                    continue

            dados_ociosos = getattr(blind_sol, "dados_nao_utilizados", [])
            if dados_ociosos:
                ociosos_reais = [
                    d for d in dados_ociosos
                    if isinstance(d, str) and not re.search(r"^(nenhum|nenhuma|n/a|nada|todos foram usados)\b", d.strip(), re.I)
                ]
                if len(ociosos_reais) > 1:
                    last_error_code = PipelineErrorCode.DADOS_OCIOSOS
                    last_error = f"Dados ociosos em excesso no enunciado/tabela ({len(ociosos_reais)} não utilizados): {'; '.join(ociosos_reais)}"
                    logger.warning(f"Tentativa {attempt}/{max_attempts} descartada por excesso de dados ociosos (Early Exit): {last_error}")
                    continue

            # --- VALIDAÇÃO ETAPA 2: CONFRONTO DIRETO DE EQUIVALÊNCIA (com Early Exit) ---
            try:
                equiv = self._run_equivalence_check(
                    resultado_solver=solver_result["correta"],
                    resultado_obtido=blind_sol.resultado_obtido
                )
            except Exception as e:
                last_error_code = PipelineErrorCode.NAO_EQUIVALENTE
                last_error = f"Falha no confronto de equivalência: {e}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na equivalência: {e}")
                continue

            if not equiv.equivalentes:
                last_error_code = PipelineErrorCode.NAO_EQUIVALENTE
                motivo = equiv.explicacao_equivalencia or "Divergência conceitual ou numérica entre o solver e a resolução cega."
                last_error = f"Divergência matemática no confronto: {motivo}"
                logger.warning(
                    f"Tentativa {attempt}/{max_attempts} descartada por divergência (Early Exit): "
                    f"Solver='{solver_result['correta']}' vs LLM='{blind_sol.resultado_obtido}' | Motivo: {motivo}"
                )
                continue

            # --- VALIDAÇÃO ETAPA 3: AUDITORIA SEMÂNTICA E PEDAGÓGICA (Chamadas Sim/Não Separadas - B3) ---
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
                continue

            if not audit.aprovada:
                if audit.complexidade_insuficiente:
                    last_error_code = PipelineErrorCode.COMPLEXIDADE
                elif audit.comando_ambiguo_ou_incompativel or audit.possui_ambiguidade or audit.desalinhamento_comando_grandeza:
                    last_error_code = PipelineErrorCode.NAO_RESPONDIVEL
                elif audit.deficit_ou_contradicao or audit.deficit_informacoes:
                    last_error_code = PipelineErrorCode.PREMISSA_OCULTA
                else:
                    last_error_code = PipelineErrorCode.AUDITORIA
                last_error = f"Rejeição semântica: {audit.motivo_rejeicao}"
                logger.warning(f"Tentativa {attempt}/{max_attempts} falhou na auditoria semântica: {audit.motivo_rejeicao}")
                continue

            logger.info(
                f"Item PoT para {clean_hab} gerado, comprovado e validado nas 3 etapas com sucesso na tentativa {attempt}! "
                f"Gabarito: {gabarito} ({alternativas[gabarito]})."
            )

            # --- PERSISTÊNCIA NO POSTGRESQL ---
            scratchpad_header = (
                f"# Planejamento PoT:\n# {pot_output.planejamento}\n\n"
                if pot_output.planejamento
                else ""
            )
            nova_questao = QuestaoInedita(
                id=uuid.uuid4(),
                habilidade_codigo=habilidade.codigo,
                enunciado=pot_output.enunciado,
                alternativas=alternativas,
                gabarito=gabarito,
                justificativa=blind_sol.resolucao_passo_a_passo,
                thought_scratchpad=f"{scratchpad_header}# Solver Python validado via PoT:\n{pot_output.solver}",
                is_validated=True
            )
            db.add(nova_questao)
            db.commit()
            db.refresh(nova_questao)
            return nova_questao

        raise ValueError(
            f"RN-Q01 (PoT): Não foi possível gerar uma questão inédita válida para {clean_hab} após {max_attempts} tentativas. "
            f"Último erro: {last_error}"
        )

    def _run_blind_solving(
        self,
        enunciado: str,
        tabela_dados: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0
    ) -> QuestaoBlindSolvingOutput:
        """
        Etapa 1 da Validação: Resolução Cega Pura.
        A LLM recebe exclusivamente o enunciado (e tabela) e deduz a resolução e o resultado obtido.
        """
        prompt = build_blind_solving_prompt(
            enunciado=enunciado,
            tabela_dados=tabela_dados
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
        """
        Etapa 2 da Validação: Confronto Direto de Equivalência Matemática.
        Avalia se a resposta calculada pelo solver e o resultado deduzido pela LLM são equivalentes.
        Aplica atalho determinístico em Python (0ms) para igualdade exata ou numérica
        antes de acionar o juiz LLM.
        """
        # 1. Atalho determinístico em Python (0ms) para igualdade textual ou numérica exata
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

        # 2. Confronto semântico via LLM quando há divergência de formato ou unidades (ex: 2500 vs R$ 2.500)
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
                # Suporte a variações semânticas se o modelo responder "sao_equivalentes"
                parsed["equivalentes"] = bool(parsed.get("sao_equivalentes", True))

        return QuestaoEquivalenciaOutput(**parsed)

    def _run_semantic_audit(
        self,
        enunciado: str,
        alternativas: Dict[str, str],
        tabela_dados: Optional[List[Dict[str, Any]]] = None,
        letra_gabarito: Optional[str] = None,
        habilidade_codigo: Optional[str] = None,
        habilidade_descricao: Optional[str] = None
    ) -> QuestaoAuditoriaSemanticaOutput:
        """
        Etapa 3 da Validação: Auditoria Semântica e Pedagógica em chamadas sim/não separadas (B3).
        Executa uma chamada por critério (temperature=0.0, saída curta) com Early Exit ao detectar defeito.
        """
        flags: Dict[str, Any] = {c: False for c in AUDITORIA_CRITERIOS_B3}
        evidencias: List[str] = []

        for criterio in AUDITORIA_CRITERIOS_B3:
            prompt = build_auditoria_criterio_prompt(
                criterio=criterio,
                enunciado=enunciado,
                alternativas=alternativas,
                tabela_dados=tabela_dados,
                letra_gabarito=letra_gabarito,
                habilidade_codigo=habilidade_codigo,
                habilidade_descricao=habilidade_descricao
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

            if isinstance(parsed, dict) and "defeito" not in parsed and (
                "incoerencia_ou_absurdo" in parsed or "possui_incoerencia" in parsed
            ):
                # Compatibilidade com mocks de testes que retornam o objeto consolidado em chamada única
                return QuestaoAuditoriaSemanticaOutput(**parsed)

            defeito = bool(parsed.get("defeito", False)) if isinstance(parsed, dict) else False
            evidencia = str(parsed.get("evidencia", "")).strip() if isinstance(parsed, dict) else ""
            flags[criterio] = defeito
            if defeito:
                if evidencia:
                    evidencias.append(f"[{criterio}] {evidencia}")
                # Early Exit na Etapa 3 ao detectar o primeiro critério reprovado
                break

        flags["analise"] = " | ".join(evidencias) if evidencias else "Item adequado."
        return QuestaoAuditoriaSemanticaOutput(**flags)

    def generate_batch(
        self,
        db: Session,
        habilidades: Optional[List[str]] = None,
        count_per_habilidade: int = 1,
        num_few_shot: int = 2,
        on_progress: Optional[Callable[[str, int, int, bool, Optional[str]], None]] = None
    ) -> BatchPopulationSummary:
        """
        Executa a geração em lote de questões inéditas para uma lista de habilidades
        ou para todas as 30 habilidades cadastradas no ENEM.
        """
        start_time = time.time()

        # Se não especificou, busca todas as habilidades cadastradas na Matriz
        if not habilidades:
            all_habs = db.query(HabilidadeEnem).order_by(HabilidadeEnem.codigo).all()
            target_codes = [h.codigo for h in all_habs]
        else:
            target_codes = [h.strip().upper() for h in habilidades]

        results: List[BatchPopulationItemResult] = []
        total_success = 0
        total_failures = 0
        total_operations = len(target_codes) * count_per_habilidade
        current_op = 0
        failed_habilidades = []

        for hab_code in target_codes:
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
                    result_item = BatchPopulationItemResult(
                        habilidade_codigo=hab_code,
                        questao_id=questao.id,
                        success=True,
                        attempts=1,
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
        limit: int = 50
    ) -> List[QuestaoInedita]:
        """Consulta questões inéditas geradas com paginação e filtro por habilidade."""
        query = db.query(QuestaoInedita)
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
