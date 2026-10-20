"""
Schemas Pydantic para validação estrutural e transferência de dados de Questões Inéditas do ENEM.
Atende a RN-Q01 (validação estrutural de unicidade e formato) e RN-Q02 (schema JSON estrito).
"""

from enum import Enum
from typing import Dict, Optional, List, Any
import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class PipelineErrorCode(str, Enum):
    """Códigos tipificados de falha na pipeline PoT (A7)."""
    SINTAXE = "SINTAXE"
    SEGURANCA = "SEGURANCA"
    TIMEOUT = "TIMEOUT"
    NOME_LIVRE = "NOME_LIVRE"
    USO_PI = "USO_PI"
    DISTRATORES_INSUFICIENTES = "DISTRATORES_INSUFICIENTES"
    ERROS_TIPICOS_INVALIDOS = "ERROS_TIPICOS_INVALIDOS"
    NEXO_NUMERICO = "NEXO_NUMERICO"
    COLISAO = "COLISAO"
    TABELA_INVALIDA = "TABELA_INVALIDA"
    TERMO_PROIBIDO = "TERMO_PROIBIDO"
    COMPLEXIDADE = "COMPLEXIDADE"
    CASO_DEGENERADO = "CASO_DEGENERADO"
    NAO_RESPONDIVEL = "NAO_RESPONDIVEL"
    PREMISSA_OCULTA = "PREMISSA_OCULTA"
    DADOS_OCIOSOS = "DADOS_OCIOSOS"
    INCONSISTENCIA_CEGA = "INCONSISTENCIA_CEGA"
    NAO_EQUIVALENTE = "NAO_EQUIVALENTE"
    AUDITORIA = "AUDITORIA"


class PipelineValidationError(ValueError):
    """Exceção tipificada da pipeline PoT que carrega um PipelineErrorCode (subclasse de ValueError)."""

    def __init__(self, code: PipelineErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class QuestaoEnunciadoSolverOutput(BaseModel):
    """
    Schema estruturado para a Fase 1 da geração Program-Aided (PoT):
    O modelo produz o planejamento, o enunciado (com tabela opcional) e o código Python do solver.
    """
    planejamento: Optional[str] = Field(
        None,
        description="Planejamento prévio dos dados, etapas de raciocínio e erros típicos dos distratores."
    )
    enunciado: str = Field(
        ...,
        description="Texto contextualizado da questão com comando final inequívoco."
    )
    tabela_dados: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Se o problema envolver tabela de dados, coloque-a aqui como uma lista de dicionários (cada dicionário é uma linha)."
    )
    erros_tipicos: Optional[List[str]] = Field(
        None,
        min_length=4,
        max_length=4,
        description="Lista com exatamente 4 erros típicos de alunos que originam as variáveis erro_* no solver."
    )
    solver: str = Field(
        ...,
        description="Função Python def resolver() calculando a resposta exata ('correta') e 4 distratores plausíveis ('erro_*')."
    )

    @field_validator("enunciado")
    @classmethod
    def validate_enunciado(cls, v: str) -> str:
        clean = v.strip()
        if len(clean) < 30:
            raise ValueError("O enunciado deve conter uma situação-problema completa (mínimo de 30 caracteres).")
        return clean

    @field_validator("tabela_dados")
    @classmethod
    def validate_tabela_dados(cls, v: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if v is None:
            return None
        if len(v) > 6:
            raise ValueError(f"TABELA_INVALIDA: 'tabela_dados' excede o limite máximo de 6 linhas (recebido: {len(v)}).")
        if len(v) > 0:
            expected_keys = list(v[0].keys())
            if not expected_keys:
                raise ValueError("TABELA_INVALIDA: as linhas de 'tabela_dados' devem conter pelo menos uma coluna.")
            expected_set = set(expected_keys)
            for idx, row in enumerate(v, 1):
                if not isinstance(row, dict) or set(row.keys()) != expected_set or len(row.keys()) != len(expected_keys):
                    raise ValueError(
                        f"TABELA_INVALIDA: todas as linhas de 'tabela_dados' devem ter exatamente as mesmas chaves. "
                        f"Chaves esperadas: {expected_keys}; linha {idx}: {list(row.keys()) if isinstance(row, dict) else type(row).__name__}."
                    )
        return v

    @field_validator("erros_tipicos", mode="before")
    @classmethod
    def validate_erros_tipicos(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        if not isinstance(v, list) or len(v) != 4:
            raise ValueError(
                f"ERROS_TIPICOS_INVALIDOS: 'erros_tipicos' deve conter exatamente 4 itens (recebido: {len(v) if isinstance(v, list) else type(v).__name__})."
            )
        cleaned = [str(item).strip() for item in v if str(item).strip()]
        if len(cleaned) != 4:
            raise ValueError("ERROS_TIPICOS_INVALIDOS: os 4 itens de 'erros_tipicos' não podem ser vazios.")
        return cleaned

    @field_validator("solver")
    @classmethod
    def validate_solver(cls, v: str) -> str:
        clean = v.strip()
        if "def resolver" not in clean:
            raise ValueError("O código do solver deve definir obrigatoriamente a função 'def resolver()'.")
        return clean


POT_PHASE1_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "planejamento": {"type": "string"},
        "enunciado": {"type": "string"},
        "tabela_dados": {
            "anyOf": [
                {"type": "array", "items": {"type": "object"}, "maxItems": 6},
                {"type": "null"}
            ]
        },
        "erros_tipicos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 4,
            "maxItems": 4
        },
        "solver": {"type": "string"}
    },
    "required": ["planejamento", "enunciado", "erros_tipicos", "solver"]
}


class QuestaoPlanejamentoEnunciadoOutput(BaseModel):
    """
    Schema para a Etapa 1a da decomposição da Fase 1:
    planejamento + enunciado + tabela_dados (opcional) + 4 erros_tipicos (sem solver).
    """
    planejamento: Optional[str] = Field(
        None,
        description="Planejamento prévio dos dados, etapas de raciocínio e erros típicos dos distratores."
    )
    enunciado: str = Field(
        ...,
        description="Texto contextualizado da questão com comando final inequívoco."
    )
    tabela_dados: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Tabela estruturada opcional (máximo 6 linhas com as mesmas chaves)."
    )
    erros_tipicos: Optional[List[str]] = Field(
        None,
        min_length=4,
        max_length=4,
        description="Lista com exatamente 4 erros típicos de alunos que originarão as variáveis erro_* no solver."
    )

    @field_validator("enunciado")
    @classmethod
    def validate_enunciado(cls, v: str) -> str:
        return QuestaoEnunciadoSolverOutput.validate_enunciado(v)

    @field_validator("tabela_dados")
    @classmethod
    def validate_tabela_dados(cls, v: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        return QuestaoEnunciadoSolverOutput.validate_tabela_dados(v)

    @field_validator("erros_tipicos", mode="before")
    @classmethod
    def validate_erros_tipicos(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return QuestaoEnunciadoSolverOutput.validate_erros_tipicos(v)


POT_PHASE1A_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "planejamento": {"type": "string"},
        "enunciado": {"type": "string"},
        "tabela_dados": {
            "anyOf": [
                {"type": "array", "items": {"type": "object"}, "maxItems": 6},
                {"type": "null"}
            ]
        },
        "erros_tipicos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 4,
            "maxItems": 4
        }
    },
    "required": ["planejamento", "enunciado", "erros_tipicos"]
}

POT_PHASE1B_SOLVER_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "solver": {"type": "string"}
    },
    "required": ["solver"]
}


class QuestaoJustificativaOutput(BaseModel):
    """
    Schema estruturado para a justificativa pedagógica.
    """
    justificativa: str = Field(
        ...,
        description="Explicação pedagógica passo a passo comprovando o gabarito e apontando o erro nos distratores."
    )


class QuestaoBlindSolvingOutput(BaseModel):
    """
    Schema para a Chamada 1 da Fase de Validação: Resolução Cega Pura.
    """
    resolucao_passo_a_passo: str = Field(
        ...,
        description="Resolução didática completa e detalhada passo a passo deduzindo o resultado a partir do enunciado."
    )
    resultado_obtido: Any = Field(
        ...,
        description="Valor final deduzido no formato de tipo primário do Python (int, float, str, dict ou list)."
    )
    premissas_assumidas: List[str] = Field(
        default_factory=list,
        description="Premissas ou convenções implícitas que precisaram ser adotadas sem estar escritas no enunciado."
    )
    dados_nao_utilizados: List[str] = Field(
        default_factory=list,
        description="Números ou colunas fornecidos que não foram utilizados no cálculo."
    )
    pergunta_respondivel: bool = Field(
        True,
        description="False se o comando final não puder ser respondido numericamente com os dados fornecidos."
    )


class QuestaoEquivalenciaOutput(BaseModel):
    """
    Schema para a Chamada 2 da Fase de Validação: Confronto Direto de Equivalência.
    """
    equivalentes: bool = Field(
        ...,
        description="True se os dois resultados expressam a mesma resposta matemática/conceitual."
    )
    explicacao_equivalencia: Optional[str] = Field(
        None,
        description="Explicação objetiva da equivalência ou discrepância encontrada."
    )


class QuestaoAuditoriaSemanticaOutput(BaseModel):
    """
    Schema para a Chamada 3 da Fase de Validação: Auditoria Semântica e Pedagógica.
    Avalia a presença de defeitos no item através de critérios semânticos e pedagógicos (B3).
    """
    analise: Optional[str] = Field(
        None,
        description="Evidência curta dos problemas identificados ou 'Item adequado'."
    )
    incoerencia_ou_absurdo: bool = Field(
        False,
        description="True se a situação for absurda, fisicamente incoerente ou conceitualmente errada."
    )
    comando_ambiguo_ou_incompativel: bool = Field(
        False,
        description="True se o comando for dúbio, não informar unidade ou não pedir um valor numérico."
    )
    deficit_ou_contradicao: bool = Field(
        False,
        description="True se faltarem informações indispensáveis ou se texto e tabela se contradisserem."
    )
    desalinhamento_comando_grandeza: bool = Field(
        False,
        description="True se o comando final NÃO perguntar exatamente a grandeza definida no enunciado/gabarito (B3a)."
    )
    fuga_habilidade_alvo: bool = Field(
        False,
        description="True se a resolução da questão NÃO exigir a habilidade-alvo especificada (B3b)."
    )
    complexidade_insuficiente: bool = Field(
        False,
        description="Sinal secundário: True se o item for trivial demais para o ENEM (operação direta única)."
    )

    # Campos legados mantidos para compatibilidade retroativa com testes
    possui_incoerencia: Optional[bool] = None
    possui_ambiguidade: Optional[bool] = None
    deficit_informacoes: Optional[bool] = None
    erros_ou_vazamentos: Optional[bool] = None
    duplicacao_tabelas: Optional[bool] = None

    @property
    def aprovada(self) -> bool:
        novas_flags = [
            self.incoerencia_ou_absurdo,
            self.comando_ambiguo_ou_incompativel,
            self.deficit_ou_contradicao,
            self.desalinhamento_comando_grandeza,
            self.fuga_habilidade_alvo,
            self.complexidade_insuficiente
        ]
        flags_legadas = [
            bool(self.possui_incoerencia),
            bool(self.possui_ambiguidade),
            bool(self.deficit_informacoes),
            bool(self.erros_ou_vazamentos),
            bool(self.duplicacao_tabelas)
        ]
        return not any(novas_flags) and not any(flags_legadas)

    @property
    def motivo_rejeicao(self) -> Optional[str]:
        motivos = []
        if self.incoerencia_ou_absurdo or self.possui_incoerencia:
            motivos.append("Incoerência semântica ou física na situação-problema.")
        if self.comando_ambiguo_ou_incompativel or self.possui_ambiguidade:
            motivos.append("Comando ambíguo, sem unidade clara ou incompatível com resposta numérica.")
        if self.deficit_ou_contradicao or self.deficit_informacoes:
            motivos.append("Déficit de dados essenciais ou contradição entre texto e tabela.")
        if self.desalinhamento_comando_grandeza:
            motivos.append("Desalinhamento entre a grandeza definida no enunciado e o que o comando final pergunta.")
        if self.fuga_habilidade_alvo:
            motivos.append("A questão não exige a habilidade-alvo da Matriz de Referência do ENEM.")
        if self.complexidade_insuficiente:
            motivos.append("Complexidade insuficiente para o ENEM (item trivial de operação direta).")
        if self.erros_ou_vazamentos:
            motivos.append("Presença de erros gramaticais ou termos proibidos de código.")
        if self.duplicacao_tabelas:
            motivos.append("Redundância ou repetição de dados da tabela no enunciado.")
        if self.analise and not self.aprovada:
            motivos.append(f"Análise do Revisor: {self.analise}")
        return " | ".join(motivos) if motivos else None


class QuestaoIneditaLLMOutput(BaseModel):
    """
    Schema estrito para a saída estruturada do LLM Qwen 2.5 via Ollama (format='json').
    """
    enunciado: str = Field(
        ...,
        description="Texto-base contextualizado e comando da questão, no padrão do ENEM."
    )
    tabela_dados: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Se o problema envolver tabela de dados, coloque-a aqui como uma lista de dicionários (cada dicionário é uma linha)."
    )
    alternativas: Dict[str, str] = Field(
        ...,
        description="Dicionário com exatamente 5 alternativas identificadas pelas chaves 'A', 'B', 'C', 'D' e 'E'."
    )
    gabarito: str = Field(
        ...,
        description="Letra da alternativa correta única ('A', 'B', 'C', 'D' ou 'E')."
    )
    justificativa: str = Field(
        ...,
        description="Resolução detalhada passo a passo e justificativa do porquê dos distratores estarem incorretos."
    )
    thought_scratchpad: Optional[str] = Field(
        None,
        description="Raciocínio Chain-of-Thought interno percorrido pelo modelo durante o planejamento do item."
    )

    @field_validator("gabarito")
    @classmethod
    def validate_gabarito(cls, v: str) -> str:
        clean_v = v.strip().upper()
        if clean_v not in {"A", "B", "C", "D", "E"}:
            raise ValueError(f"Gabarito deve ser exatamente uma das letras A, B, C, D ou E. Recebido: '{v}'")
        return clean_v

    @field_validator("alternativas")
    @classmethod
    def validate_alternativas(cls, v: Dict[str, str]) -> Dict[str, str]:
        expected_keys = {"A", "B", "C", "D", "E"}
        normalized_keys = {k.strip().upper(): str(val).strip() for k, val in v.items()}
        
        if set(normalized_keys.keys()) != expected_keys:
            raise ValueError(
                f"As alternativas devem conter exatamente as chaves A, B, C, D, E. "
                f"Chaves recebidas: {sorted(list(normalized_keys.keys()))}"
            )

        for letter, text in normalized_keys.items():
            if not text:
                raise ValueError(f"O texto da alternativa '{letter}' não pode ser vazio.")

        # RN-Q01: Ausência de alternativas duplicadas
        vals = [text.strip().lower() for text in normalized_keys.values()]
        if len(set(vals)) != len(vals):
            raise ValueError("RN-Q01 violada: foram encontradas alternativas com textos idênticos/duplicados.")

        return normalized_keys

    @field_validator("enunciado")
    @classmethod
    def validate_enunciado(cls, v: str) -> str:
        clean = v.strip()
        if len(clean) < 40:
            raise ValueError(f"Enunciado muito curto ({len(clean)} caracteres) para o padrão contextualizado do ENEM.")
        return clean


class QuestaoIneditaBase(BaseModel):
    habilidade_codigo: str = Field(..., description="Código da Habilidade da Matriz de Referência (ex: 'H01')")
    enunciado: str = Field(..., description="Enunciado completo da questão")
    alternativas: Dict[str, str] = Field(..., description="Dicionário com as alternativas A, B, C, D, E")
    gabarito: str = Field(..., description="Letra do gabarito oficial ('A' a 'E')")
    justificativa: str = Field(..., description="Justificativa da resposta e resolução")
    thought_scratchpad: Optional[str] = None
    is_validated: bool = True


class QuestaoIneditaCreate(QuestaoIneditaBase):
    pass


class QuestaoIneditaResponse(QuestaoIneditaBase):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class QuestaoGenerateRequest(BaseModel):
    habilidade_codigo: str = Field(
        ...,
        description="Código da habilidade da Matriz do ENEM para gerar o item (ex: 'H01')"
    )
    num_few_shot_examples: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Quantidade de itens reais de treino do acervo a injetar no prompt (padrão 2)"
    )
    tema: Optional[str] = Field(
        None,
        description="Tema contextual opcional (ex: 'Saúde', 'Transporte'). Se omitido, é sorteado aleatoriamente."
    )
    abertura: Optional[str] = Field(
        None,
        description="Estilo de abertura narrativa opcional (ex: 'pesquisa amostral'). Se omitido, é sorteado aleatoriamente."
    )


class BatchPopulationRequest(BaseModel):
    habilidades: Optional[List[str]] = Field(
        None,
        description="Lista de códigos de habilidades específicas (ex: ['H01', 'H02']). Se omitido, processa todas as 30."
    )
    count_per_habilidade: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Número de questões inéditas a gerar por habilidade (padrão 1)"
    )
    num_few_shot_examples: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Número de exemplos históricos few-shot a usar no prompt"
    )


class BatchPopulationItemResult(BaseModel):
    habilidade_codigo: str
    questao_id: Optional[uuid.UUID] = None
    success: bool
    attempts: int
    error: Optional[str] = None
    elapsed_seconds: float


class BatchPopulationSummary(BaseModel):
    total_habilidades_processadas: int
    total_sucesso: int
    total_falhas: int
    tempo_total_segundos: float
    habilidades_com_erro: List[str] = Field(default_factory=list, description="Lista de códigos das habilidades que falharam em todas as tentativas")
    itens: List[BatchPopulationItemResult]
