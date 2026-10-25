"""
Schemas Pydantic para validação estrutural e dados de questões inéditas do ENEM.
"""

from enum import Enum
from typing import Dict, Optional, List, Any
import uuid
from pydantic import BaseModel, Field, field_validator


class PipelineErrorCode(str, Enum):
    """Códigos de falha na pipeline PoT."""
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
    NAO_EQUIVALENTE = "NAO_EQUIVALENTE"
    AUDITORIA = "AUDITORIA"


class PipelineValidationError(ValueError):
    """Exceção tipificada da pipeline PoT que carrega um PipelineErrorCode (subclasse de ValueError)."""

    def __init__(self, code: PipelineErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


HABILIDADES_DESABILITADAS: frozenset[str] = frozenset({"H06", "H20"})

MOTIVOS_HABILIDADES_DESABILITADAS: Dict[str, str] = {
    "H06": (
        "Habilidade H06 (localização e movimentação em mapas, croquis e representações bidimensionais) "
        "desabilitada: requer interpretação visual e possui amostragem insuficiente sem imagem nos microdados históricos "
        "extrapolando a delimitação deste projeto para LLMs exclusivamente textuais."
    ),
    "H20": (
        "Habilidade H20 (interpretação de gráfico cartesiano representando relações entre grandezas) "
        "desabilitada: requer interpretação visual de curvas e gráficos cartesianos e possui amostragem insuficiente sem imagem nos "
        "microdados históricos, extrapolando a delimitação deste projeto para LLMs exclusivamente textuais."
    ),
}


class HabilidadeDesabilitadaError(ValueError):
    """Exceção levantada ao tentar gerar questões para habilidades desabilitadas (H06 ou H20)."""

    def __init__(self, habilidade_codigo: str, message: Optional[str] = None):
        self.habilidade_codigo = habilidade_codigo
        msg = message or (
            f"A geração de questões para a habilidade '{habilidade_codigo}' está desabilitada. "
            f"Motivo: {MOTIVOS_HABILIDADES_DESABILITADAS.get(habilidade_codigo, 'Habilidade desabilitada por requerer interpretação visual e amostragem histórica insuficiente sem imagens.')}"
        )
        super().__init__(msg)
        self.message = msg


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
    Schema para a Fase 2A da decomposição PoT (Etapa 2):
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
    Schema para auditoria semântica e pedagógica da questão.
    """
    analise: Optional[str] = Field(
        None,
        description="Evidência dos problemas identificados ou 'Item adequado'."
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
        description="True se o comando final não perguntar a grandeza solicitada."
    )
    fuga_habilidade_alvo: bool = Field(
        False,
        description="True se a resolução da questão não exigir a habilidade-alvo especificada."
    )
    complexidade_insuficiente: bool = Field(
        False,
        description="True se o item for trivial demais para o ENEM (operação direta única)."
    )

    @property
    def aprovada(self) -> bool:
        return not any([
            self.incoerencia_ou_absurdo,
            self.comando_ambiguo_ou_incompativel,
            self.deficit_ou_contradicao,
            self.desalinhamento_comando_grandeza,
            self.fuga_habilidade_alvo,
            self.complexidade_insuficiente
        ])

    @property
    def motivo_rejeicao(self) -> Optional[str]:
        motivos = []
        if self.incoerencia_ou_absurdo:
            motivos.append("Incoerência semântica ou física na situação-problema.")
        if self.comando_ambiguo_ou_incompativel:
            motivos.append("Comando ambíguo, sem unidade clara ou incompatível com resposta numérica.")
        if self.deficit_ou_contradicao:
            motivos.append("Déficit de dados essenciais ou contradição entre texto e tabela.")
        if self.desalinhamento_comando_grandeza:
            motivos.append("Desalinhamento entre a grandeza definida no enunciado e o que o comando final pergunta.")
        if self.fuga_habilidade_alvo:
            motivos.append("A questão não exige a habilidade-alvo da Matriz de Referência do ENEM.")
        if self.complexidade_insuficiente:
            motivos.append("Complexidade insuficiente para o ENEM (item trivial de operação direta).")
        if self.analise and not self.aprovada:
            motivos.append(f"Análise do Revisor: {self.analise}")
        return " | ".join(motivos) if motivos else None


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
    habilidades_com_erro: List[str] = Field(default_factory=list, description="Códigos das habilidades que falharam em todas as tentativas")
    itens: List[BatchPopulationItemResult]
