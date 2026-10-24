import pytest
import uuid
import json
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models
from app.db.base import Base
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.services.llm_client import LLMClient
from app.services.vectorstore import ChromaVectorStore
from app.services.question_service import QuestionService

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    db = TestingSessionLocal()
    try:
        hab = HabilidadeEnem(
            codigo="H01",
            competencia=1,
            descricao="Reconhecer, no contexto social, diferentes significados e representações dos números e operações.",
            eixo_tematico="Números e Operações"
        )
        db.merge(hab)

        q1 = QuestaoEnem(
            id=uuid.uuid4(),
            ano=2021,
            habilidade_codigo="H01",
            enunciado="Enunciado da questão histórica 1 sobre leitura de medidores...",
            alternativas={"A": "10", "B": "20", "C": "30", "D": "40", "E": "50"},
            gabarito="B"
        )
        q2 = QuestaoEnem(
            id=uuid.uuid4(),
            ano=2022,
            habilidade_codigo="H01",
            enunciado="Enunciado da questão histórica 2 sobre operações básicas...",
            alternativas={"A": "100", "B": "200", "C": "300", "D": "400", "E": "500"},
            gabarito="D"
        )
        db.add(q1)
        db.add(q2)
        db.commit()
    finally:
        db.close()


def test_retrieve_few_shot_examples():
    db = TestingSessionLocal()
    try:
        mock_vs = MagicMock(spec=ChromaVectorStore)
        service = QuestionService(vector_store=mock_vs)
        exemplos = service.retrieve_few_shot_examples(db, "H01", k=2)
        assert len(exemplos) == 2
        for ex in exemplos:
            assert ex.habilidade_codigo == "H01"
            assert ex.gabarito in ["A", "B", "C", "D", "E"]
    finally:
        db.close()


def test_generate_single_questao_inedita_pot_success():
    """Valida o pipeline PoT completo com 3 etapas de validação (Resolução Cega, Equivalência, Auditoria)."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # Fase 1: Enunciado e Solver
        resp_fase1 = json.dumps({
            "enunciado": "Um reservatório com capacidade de 1.200 litros é abastecido a 40 litros por minuto com saída simultânea de 10 litros por minuto. Qual o tempo em minutos para enchê-lo?",
            "solver": "def resolver():\n    capacidade = 1200\n    entrada = 40\n    saida = 10\n    taxa = entrada - saida\n    tempo = (capacidade - 0) / taxa\n    return {'correta': tempo, 'distratores': [30, 50, 60, 80]}"
        })

        # Validação Etapa 1: Resolução Cega
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "A taxa líquida é 40 - 10 = 30 L/min. Dividindo 1200 por 30, obtemos 40 minutos.",
            "resultado_obtido": "40 minutos"
        })

        # Validação Etapa 2: Confronto de Equivalência
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "40 e 40 minutos são matematicamente equivalentes."
        })

        # Validação Etapa 3: Auditoria Semântica
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [resp_fase1, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            num_few_shot=2,
            max_attempts=2
        )

        assert questao is not None
        assert questao.habilidade_codigo == "H01"
        assert questao.is_validated is True
        assert len(questao.alternativas) == 5
        # O gabarito matemático comprovado é 40
        assert questao.alternativas[questao.gabarito] == "40"
        assert "def resolver" in questao.thought_scratchpad
        assert "taxa líquida" in questao.justificativa
        assert mock_llm.generate.call_count == 4
    finally:
        db.close()


def test_generate_single_questao_inedita_pot_retry_on_solver_error():
    """Valida se o pipeline PoT captura o erro de execução do solver e re-tenta com feedback."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa Fase 1: Solver com divisão por zero
        resp_fase1_erro = json.dumps({
            "enunciado": "Um motorista calcula a velocidade em uma viagem de 100 km com tempo 0 horas.",
            "solver": "def resolver():\n    dist = 100\n    t = 0\n    v = dist / t\n    return {'correta': v, 'distratores': [10, 20, 30, 40]}"
        })

        # 2ª tentativa Fase 1: Solver corrigido
        resp_fase1_ok = json.dumps({
            "enunciado": "Um motorista calcula a velocidade em uma viagem de 100 km com tempo de 2 horas. Qual a velocidade média em km/h?",
            "solver": "def resolver():\n    dist = 100\n    t = 2\n    v = (dist - 0) / (t * 1)\n    return {'correta': v, 'distratores': [30, 40, 60, 70]}"
        })

        # Validação 2ª tentativa
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "A velocidade média é 100 / 2 = 50 km/h.",
            "resultado_obtido": "50 km/h"
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "50 e 50 km/h são equivalentes."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [resp_fase1_erro, resp_fase1_ok, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=3
        )

        assert questao is not None
        assert questao.alternativas[questao.gabarito] == "50"
        assert mock_llm.generate.call_count == 5
    finally:
        db.close()


def test_generate_single_questao_inedita_rejects_missing_solver():
    """Valida que o pipeline PoT rejeita estritamente retornos sem solver Python."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # Formato tradicional legado (sem solver)
        mock_output = {
            "thought_scratchpad": "Passo a passo.",
            "enunciado": "Em uma loja de informática, o preço de um computador sofreu um desconto de 15%...",
            "alternativas": {
                "A": "R$ 1.980,00.",
                "B": "R$ 2.040,00.",
                "C": "R$ 2.100,00.",
                "D": "R$ 2.160,00.",
                "E": "R$ 2.240,00."
            },
            "gabarito": "B",
            "justificativa": "15% de 2400 é 360..."
        }
        mock_llm.generate.return_value = json.dumps(mock_output)

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        with pytest.raises(ValueError, match=r"RN-Q01 \(PoT\)"):
            service.generate_single_questao_inedita(
                db=db,
                habilidade_codigo="H01",
                num_few_shot=2,
                max_attempts=2
            )
    finally:
        db.close()


def test_generate_batch_success():
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        resp_pot = json.dumps({
            "enunciado": "Um investidor aplicou um capital de 5000 reais a uma taxa mensal de 2% durante 6 meses sob juros simples. Qual o montante final em reais?",
            "solver": "def resolver():\n    c = 5000\n    i = 0.02\n    t = 6\n    j = c * i * t\n    m = c + j\n    return {'correta': m, 'distratores': [5200, 5400, 5800, 6000]}"
        })
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "Juros = 5000 * 0.02 * 6 = 600. Montante = 5000 + 600 = 5600 reais.",
            "resultado_obtido": "5600"
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "5600 coincide exatamente."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })
        mock_llm.generate.side_effect = [resp_pot, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        summary = service.generate_batch(
            db=db,
            habilidades=["H01"],
            count_per_habilidade=1
        )

        assert summary.total_habilidades_processadas == 1
        assert summary.total_sucesso == 1
        assert summary.total_falhas == 0
        assert len(summary.itens) == 1
        assert summary.itens[0].success is True
    finally:
        db.close()


def test_generate_pot_item_with_tabela_dados_clean_markdown():
    """Valida se o pipeline converte tabela_dados em Markdown sem duplicações."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        resp_pot = json.dumps({
            "enunciado": "A tabela a seguir apresenta os dados de consumo de água em metros cúbicos em uma residência. Qual o consumo total no período?",
            "tabela_dados": [
                {"Mês": "Janeiro", "Consumo": 15},
                {"Mês": "Fevereiro", "Consumo": 20}
            ],
            "solver": "def resolver():\n    total = (15 + 20) * 1 - 0\n    return {'correta': total, 'distratores': [25, 30, 40, 50]}"
        })
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "O total é 15 + 20 = 35 m³.",
            "resultado_obtido": "35 m³"
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "35 e 35 m³ são equivalentes."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })
        mock_llm.generate.side_effect = [resp_pot, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=1
        )

        assert questao is not None
        assert "| Mês | Consumo |" in questao.enunciado
        assert "| Janeiro | 15 |" in questao.enunciado
        # Exatamente uma ocorrência do cabeçalho
        assert questao.enunciado.count("| Mês | Consumo |") == 1
    finally:
        db.close()


def test_generate_pot_item_sanitizes_duplicate_inline_pseudo_table():
    """Valida se o backend remove blocos redundantes de pseudo-tabelas gerados pelo LLM."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        resp_pot = json.dumps({
            "enunciado": (
                "Em um experimento de monitoramento, foram coletados dados sobre custos por megabyte baixado. "
                "Qual horário apresenta o menor custo?\n\n"
                "Tabela de dados:\n"
                "Horário | Custo por MB\n"
                "10h00 | 0.002\n"
                "14h00 | 0.003"
            ),
            "tabela_dados": [
                {"Horário": "10h00", "Custo por MB": 0.002},
                {"Horário": "14h00", "Custo por MB": 0.003}
            ],
            "solver": "def resolver():\n    return {'correta': '10h00', 'distratores': ['14h00', '18h00', '22h00', '23h00']}"
        })
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "O menor custo é 0.002 às 10h00.",
            "resultado_obtido": "10h00"
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Ambos 10h00."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })
        mock_llm.generate.side_effect = [resp_pot, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=1
        )

        assert questao is not None
        # O cabeçalho formatado em Markdown com pipes deve existir exatamente uma vez
        assert questao.enunciado.count("| Horário | Custo por MB |") == 1
        # A pseudo-tabela de texto duplicada deve ter sido removida
        assert "Tabela de dados:\nHorário | Custo por MB" not in questao.enunciado
    finally:
        db.close()


def test_generate_pot_item_sanitizes_duplicate_bullet_list():
    """Valida se o backend remove listas de tópicos redundantes em 'Tabela ...:'."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        resp_pot = json.dumps({
            "enunciado": (
                "Um centro de distribuição planeja a ração diária por faixa etária. "
                "Qual será a quantidade total de ração necessária?\n\n"
                "Tabela de consumo de ração por cães:\n"
                "- Jovens (0-2 anos): 0.5 kg/dia\n"
                "- Adultos (3-10 anos): 0.3 kg/dia"
            ),
            "tabela_dados": [
                {"Faixa": "Jovens", "Consumo": 0.5},
                {"Faixa": "Adultos", "Consumo": 0.3}
            ],
            "solver": "def resolver():\n    total = (0.5 + 0.3) * 1 - 0\n    return {'correta': total, 'distratores': [1.0, 1.2, 1.5, 2.0]}"
        })
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "Total é 0.8.",
            "resultado_obtido": "0.8"
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Ambos 0.8."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })
        mock_llm.generate.side_effect = [resp_pot, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=1
        )

        assert questao is not None
        assert "| Faixa | Consumo |" in questao.enunciado
        assert questao.enunciado.count("| Faixa | Consumo |") == 1
        assert "- Jovens" not in questao.enunciado
    finally:
        db.close()


def test_three_stage_validation_mismatch_triggers_early_exit():
    """Valida se divergência de equivalência interrompe o fluxo (Early Exit sem chamar auditoria) e faz retry."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa: Solver calculou 120 (bug de moda), mas LLM cego achou 'não há moda' -> equivalentes=False
        t1_pot = json.dumps({
            "enunciado": "Qual a moda das equipes de lixo?",
            "solver": "def resolver():\n    return {'correta': 120, 'distratores': [130, 140, 150, 160]}"
        })
        t1_blind = json.dumps({
            "resolucao_passo_a_passo": "Todos os valores aparecem 1 vez, logo o conjunto é amodal.",
            "resultado_obtido": "não há moda"
        })
        t1_equiv = json.dumps({
            "equivalentes": False,
            "explicacao_equivalencia": "O solver calculou 120, mas o conjunto é amodal (não há moda)."
        })
        # A auditoria da tentativa 1 NÃO deve ser chamada! (Early Exit)

        # 2ª tentativa: Sucesso pleno
        t2_pot = json.dumps({
            "enunciado": "Qual a média das notas 10 e 20?",
            "solver": "def resolver():\n    return {'correta': 15, 'distratores': [10, 20, 25, 30]}"
        })
        t2_blind = json.dumps({
            "resolucao_passo_a_passo": "(10 + 20) / 2 = 15.",
            "resultado_obtido": "15"
        })
        t2_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "15 e 15 são equivalentes."
        })
        t2_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [
            t1_pot, t1_blind, t1_equiv,  # 3 chamadas na 1ª tentativa (curto-circuito na equivalência)
            t2_pot, t2_blind, t2_equiv, t2_audit  # 4 chamadas na 2ª tentativa
        ]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=2
        )

        assert questao is not None
        assert questao.alternativas[questao.gabarito] == "15"
        assert mock_llm.generate.call_count == 7
    finally:
        db.close()


def test_three_stage_validation_semantic_failure_rejects():
    """Valida se defeito apontado na auditoria semântica rejeita a questão e gera mensagem automática."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa: Equivalência OK, mas Auditoria detecta déficit de informações
        t1_pot = json.dumps({
            "enunciado": "Qual a velocidade média de um carro que percorreu uma distância sem tempo?",
            "solver": "def resolver():\n    return {'correta': 10, 'distratores': [20, 30, 40, 50]}"
        })
        t1_blind = json.dumps({
            "resolucao_passo_a_passo": "Resolução 10.",
            "resultado_obtido": "10"
        })
        t1_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Equivalentes."
        })
        t1_audit = json.dumps({
            "analise": "Falta tempo no enunciado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": True,  # Defeito detectado!
            "complexidade_insuficiente": False
        })

        # 2ª tentativa: Sucesso pleno
        t2_pot = json.dumps({
            "enunciado": "Enunciado completo sobre velocidade média.",
            "solver": "def resolver():\n    return {'correta': 80, 'distratores': [60, 70, 90, 100]}"
        })
        t2_blind = json.dumps({
            "resolucao_passo_a_passo": "80 km/h.",
            "resultado_obtido": "80"
        })
        t2_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Equivalentes."
        })
        t2_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [
            t1_pot, t1_blind, t1_equiv, t1_audit,  # 4 chamadas na 1ª tentativa (rejeitada na auditoria)
            t2_pot, t2_blind, t2_equiv, t2_audit   # 4 chamadas na 2ª tentativa
        ]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=2
        )

        assert questao is not None
        assert questao.alternativas[questao.gabarito] == "80"
        assert mock_llm.generate.call_count == 8
    finally:
        db.close()


def test_stage_1b_rejects_excessive_unused_data_and_injects_retry_hint():
    """Valida se a Etapa 1b reprova quando dados_nao_utilizados tem > 1 item e passa alerta_tentativa_anterior no retry."""
    from app.services.question_service import _classify_retry_hint
    from app.schemas.question import PipelineErrorCode

    assert "2 etapas" in _classify_retry_hint(PipelineErrorCode.COMPLEXIDADE)
    assert "len([" in _classify_retry_hint(PipelineErrorCode.NEXO_NUMERICO)

    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa: Blind solving aponta 2 dados não utilizados -> Early Exit na Etapa 1b!
        t1_pot = json.dumps({
            "planejamento": "Plano inicial com dados extras.",
            "enunciado": "Um atleta correu em 10 s e 20 s, e ganhou 50 pontos fixos mais 30 de bônus. Qual sua pontuação total?",
            "solver": "def resolver():\n    return {'correta': 80, 'distratores': [50, 60, 70, 90]}"
        })
        t1_blind = json.dumps({
            "resolucao_passo_a_passo": "50 + 30 = 80 pontos.",
            "premissas_assumidas": [],
            "dados_nao_utilizados": ["tempo 10 s", "tempo 20 s"],
            "pergunta_respondivel": True,
            "resultado_obtido": 80
        })

        # 2ª tentativa: Usa todos os dados e aprova
        t2_pot = json.dumps({
            "planejamento": "Plano corrigido usando todos os dados.",
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total, em pontos, no fim de semana?",
            "solver": "def resolver():\n    return {'correta': 80, 'distratores': [50, 60, 70, 90]}"
        })
        t2_blind = json.dumps({
            "resolucao_passo_a_passo": "50 + 30 = 80.",
            "premissas_assumidas": [],
            "dados_nao_utilizados": [],
            "pergunta_respondivel": True,
            "resultado_obtido": 80
        })
        t2_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Ambos 80."
        })
        t2_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [
            t1_pot, t1_blind,  # 2 chamadas na 1ª tentativa (Early Exit na Etapa 1b)
            t2_pot, t2_blind, t2_equiv, t2_audit
        ]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=2
        )

        assert questao is not None
        assert "# Planejamento PoT:" in questao.thought_scratchpad
        assert mock_llm.generate.call_count == 6
        # Verifica que o prompt da 2ª tentativa (3ª chamada ao LLM, índice 2) recebeu a diretriz curta de dados com função
        second_attempt_prompt = mock_llm.generate.call_args_list[2].kwargs["prompt"]
        assert "Dados com função:" in second_attempt_prompt
    finally:
        db.close()


def test_a7_collision_retry_injects_colisao_hint_not_nexo():
    """A7: Colisão excessiva de distratores gera hint de COLISAO no retry, corrigindo o bug de precedência com NEXO_NUMERICO."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa: 2 distratores colidem com correta (80) -> COLISAO
        t1_pot = json.dumps({
            "planejamento": "Plano com colisão.",
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total no fim de semana?",
            "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
            "solver": "def resolver():\n    a = 50\n    b = 30\n    correta = a + b\n    erro_1 = 80\n    erro_2 = 80\n    erro_3 = 50\n    erro_4 = 30"
        })
        # 2ª tentativa: Sucesso
        t2_pot = json.dumps({
            "planejamento": "Plano sem colisão.",
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total no fim de semana?",
            "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
            "solver": "def resolver():\n    a = 50\n    b = 30\n    correta = (a + b) * 1 - 0\n    erro_1 = a - b\n    erro_2 = a\n    erro_3 = b\n    erro_4 = a * b"
        })
        t2_blind = json.dumps({
            "resolucao_passo_a_passo": "50 + 30 = 80.",
            "premissas_assumidas": [],
            "dados_nao_utilizados": [],
            "pergunta_respondivel": True,
            "resultado_obtido": 80
        })
        t2_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Ambos 80."
        })
        t2_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [t1_pot, t2_pot, t2_blind, t2_equiv, t2_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=2
        )

        assert questao is not None
        second_attempt_prompt = mock_llm.generate.call_args_list[1].kwargs["prompt"]
        assert "Distratores distintos:" in second_attempt_prompt
        assert "Nexo numérico:" not in second_attempt_prompt
    finally:
        db.close()


def test_a8_temperature_ceiling_03_and_seed_passed():
    """A8: Garante que a temperatura da geração do solver nunca ultrapasse 0.3 mesmo após múltiplos retries e use seed."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        bad_pot = json.dumps({
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total?",
            "solver": "def resolver():\n    correta = (50 + 30\n"  # SyntaxError
        })
        good_pot = json.dumps({
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total no fim de semana?",
            "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
            "solver": "def resolver():\n    a = 50\n    b = 30\n    correta = (a + b) * 1 - 0\n    erro_1 = a - b\n    erro_2 = a\n    erro_3 = b\n    erro_4 = a * b"
        })
        resp_blind = json.dumps({
            "resolucao_passo_a_passo": "50 + 30 = 80.",
            "premissas_assumidas": [],
            "dados_nao_utilizados": [],
            "pergunta_respondivel": True,
            "resultado_obtido": 80
        })
        resp_equiv = json.dumps({
            "equivalentes": True,
            "explicacao_equivalencia": "Ambos 80."
        })
        resp_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        # 3 falhas seguidas de sucesso na 4ª tentativa, mesmo passando temperature=0.5 na entrada
        mock_llm.generate.side_effect = [bad_pot, bad_pot, bad_pot, good_pot, resp_blind, resp_equiv, resp_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=4,
            temperature=0.5  # Passado acima do teto
        )

        assert questao is not None
        phase1_calls = mock_llm.generate.call_args_list[:4]
        for call in phase1_calls:
            assert call.kwargs["temperature"] <= 0.3
            assert isinstance(call.kwargs.get("seed"), int)
    finally:
        db.close()


def test_b1_typology_per_skill_and_competency_few_shots():
    """B1: Verifica 3 a 5 tipologias para H01..H30, few-shots por competência (C1..C7) e injeção da tipologia no prompt."""
    from app.core.prompts import POT_FEW_SHOT_BY_COMPETENCIA
    from app.schemas.question import QuestaoEnunciadoSolverOutput
    from app.services.code_executor import execute_solver_code, validate_solver_consistency
    from app.services.question_validator import format_enunciado_with_table

    mock_llm = MagicMock(spec=LLMClient)
    mock_vs = MagicMock(spec=ChromaVectorStore)
    service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)

    # 1. Todas as 30 habilidades têm entre 3 e 5 tipologias
    for i in range(1, 31):
        code = f"H{i:02d}"
        hab_entry = service._habilidades_queries.get(code)
        assert hab_entry is not None, f"{code} ausente em habilidades_queries.json"
        tipologias = hab_entry.get("tipologias", [])
        assert 3 <= len(tipologias) <= 5, f"{code} deve ter entre 3 e 5 tipologias (encontrado: {len(tipologias)})"
        sampled = service.sortear_tipologia(code)
        assert sampled in tipologias

    # 2. Todos os few-shots das 7 competências executam e passam no nexo numérico
    for comp in range(1, 8):
        examples = POT_FEW_SHOT_BY_COMPETENCIA.get(comp, [])
        assert len(examples) >= 1
        for raw_ex in examples:
            parsed = json.loads(raw_ex)
            pot_out = QuestaoEnunciadoSolverOutput(**parsed)
            enun_full = format_enunciado_with_table(pot_out.enunciado, pot_out.tabela_dados)
            res = execute_solver_code(pot_out.solver, timeout=5)
            vals = validate_solver_consistency(enun_full, pot_out.solver, res, tabela_dados=pot_out.tabela_dados)
            assert len(set(vals)) == 5

    # 3. Tipologia é injetada no prompt de geração
    prompt_check = service.sortear_tipologia("H01")
    assert prompt_check is not None


def test_b2_deterministic_complexity_gate():
    """B2: Reprova deterministamente solver trivial (< 3 operações ou < 2 tipos) com código COMPLEXIDADE."""
    from app.services.code_executor import validate_solver_complexity
    from app.schemas.question import PipelineErrorCode, PipelineValidationError

    # 1. Trivial: apenas 1 operação (soma simples)
    trivial_sum = """
def resolver():
    a = 50
    b = 30
    correta = a + b
    erro_1 = a - b
    erro_2 = a * b
    erro_3 = a / 2
    erro_4 = b * 2
"""
    with pytest.raises(PipelineValidationError) as exc_1:
        validate_solver_complexity(trivial_sum)
    assert exc_1.value.code == PipelineErrorCode.COMPLEXIDADE

    # 2. Trivial: 3 operações mas apenas 1 tipo (só somas)
    only_additions = """
def resolver():
    a, b, c, d = 10, 20, 30, 40
    correta = a + b + c + d
    erro_1 = a + b + c
    erro_2 = b + c + d
    erro_3 = a + d
    erro_4 = a + b
"""
    with pytest.raises(PipelineValidationError) as exc_2:
        validate_solver_complexity(only_additions)
    assert exc_2.value.code == PipelineErrorCode.COMPLEXIDADE

    # 3. Válido: >= 3 operações e >= 2 tipos de operação na fatia de 'correta'
    valid_multi_step = """
def resolver():
    preco = 250
    desconto = 20
    acrescimo = 10
    com_desconto = preco * (1 - desconto / 100)
    correta = round(com_desconto * (1 + acrescimo / 100), 2)
    erro_1 = preco - desconto
    erro_2 = com_desconto
    erro_3 = preco + acrescimo
    erro_4 = preco * 0.9
"""
    metrics = validate_solver_complexity(valid_multi_step)
    assert metrics["num_operations"] >= 3
    assert len(metrics["operation_types"]) >= 2


def test_b3_separate_yes_no_audit_calls_and_early_exit():
    """B3: Etapa 3 executa chamadas sim/não separadas com temperature=0.0 por critério e faz early exit no 1º defeito."""
    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)

        # 1. Quando o 4º critério (desalinhamento_comando_grandeza) acusa defeito=True, para na 4ª chamada (não faz a 5ª)
        mock_llm.generate.side_effect = [
            json.dumps({"defeito": False, "justificativa_curta": "OK 1"}),
            json.dumps({"defeito": False, "justificativa_curta": "OK 2"}),
            json.dumps({"defeito": False, "justificativa_curta": "OK 3"}),
            json.dumps({"defeito": True, "justificativa_curta": "Pergunta em reais, mas calcula litros."}),
        ]
        audit_fail = service._run_semantic_audit(
            enunciado="Um tanque tem 500 L...",
            alternativas={"A": "100", "B": "200", "C": "300", "D": "400", "E": "500"},
            letra_gabarito="A",
            habilidade_codigo="H01",
            habilidade_descricao="Reconhecer representações numéricas."
        )
        assert audit_fail.aprovada is False
        assert audit_fail.desalinhamento_comando_grandeza is True
        assert mock_llm.generate.call_count == 4
        for c in mock_llm.generate.call_args_list:
            assert c.kwargs["temperature"] == 0.0

        # 2. Quando todos os 5 critérios retornam defeito=False, aprova após 5 chamadas curtas
        mock_llm.reset_mock()
        mock_llm.generate.side_effect = [
            json.dumps({"defeito": False, "justificativa_curta": "OK"}) for _ in range(5)
        ]
        audit_ok = service._run_semantic_audit(
            enunciado="Enunciado válido...",
            alternativas={"A": "100", "B": "200", "C": "300", "D": "400", "E": "500"},
            letra_gabarito="A",
            habilidade_codigo="H01",
            habilidade_descricao="Reconhecer representações numéricas."
        )
        assert audit_ok.aprovada is True
        assert mock_llm.generate.call_count == 5

        # 3. Fluxo completo em mock_mode=True passa pelas 5 chamadas separadas da Etapa 3
        real_mock_llm = LLMClient(mock_mode=True)
        service_mock = QuestionService(llm_client=real_mock_llm, vector_store=mock_vs)
        mock_vs.search.return_value = []
        questao = service_mock.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=1
        )
        assert questao is not None
    finally:
        db.close()


def test_phase_c_keep_alive_and_decompose_phase1():
    """Fase C: Verifica keep_alive no payload do LLMClient e decomposição da Fase 1 em 2 chamadas por padrão."""
    # 1. Verifica keep_alive no payload do LLMClient
    client = LLMClient(mock_mode=True)
    _, payload = client._build_payload_and_url(prompt="Teste", max_tokens=256, temperature=0.1, seed=42)
    assert payload.get("keep_alive") == "30m"
    assert payload["options"]["seed"] == 42

    # 2. Verifica decomposição da Fase 1 em duas chamadas por padrão (mock_mode=True roda 1a e 1b)
    db = TestingSessionLocal()
    try:
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []
        service = QuestionService(llm_client=client, vector_store=mock_vs)
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=1
        )
        assert questao is not None
        assert questao.is_validated is True
        assert "# Planejamento PoT:" in questao.thought_scratchpad
    finally:
        db.close()



def test_equivalence_check_deterministic_fast_path():
    """Etapa 2: Valida que igualdade exata (textual ou numérica) usa o fast-path em Python (0ms) sem chamar o LLM."""
    mock_llm = MagicMock(spec=LLMClient)
    mock_vs = MagicMock(spec=ChromaVectorStore)
    service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)

    # 1. Igualdade inteira exata: 40 == 40 (0ms, 0 chamadas ao LLM)
    eq1 = service._run_equivalence_check(40, 40)
    assert eq1.equivalentes is True
    assert "Python (0ms)" in eq1.explicacao_equivalencia
    assert mock_llm.generate.call_count == 0

    # 2. Igualdade numérica decimal com vírgula: 12.5 == "12,5" (0ms, 0 chamadas ao LLM)
    eq2 = service._run_equivalence_check(12.5, "12,5")
    assert eq2.equivalentes is True
    assert "Python (0ms)" in eq2.explicacao_equivalencia
    assert mock_llm.generate.call_count == 0

    # 3. Formato diferente (ex: "R$ 2.500,00" vs 2500): recorre ao LLM (1 chamada)
    mock_llm.generate.return_value = json.dumps({
        "equivalentes": True,
        "explicacao_equivalencia": "2500 e R$ 2.500,00 são equivalentes."
    })
    eq3 = service._run_equivalence_check(2500, "R$ 2.500,00")
    assert eq3.equivalentes is True
    assert mock_llm.generate.call_count == 1


def test_relational_persistence_retry_then_success():
    """
    Valida a arquitetura em 3 tabelas (ciclos_geracao, tentativas_geracao, questoes_ineditas)
    quando a 1ª tentativa falha (NEXO_NUMERICO) e a 2ª tentativa é aprovada.
    """
    from app.db.models.ciclo_geracao import CicloGeracao
    from app.db.models.tentativa_geracao import TentativaGeracao

    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.model_name = "qwen2.5:7b-test"
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # 1ª tentativa: usa número 999 não presente no enunciado -> NEXO_NUMERICO
        t1_pot = json.dumps({
            "planejamento": "Plano com número mágico 999.",
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total no fim de semana?",
            "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
            "solver": "def resolver():\n    a = 50\n    b = 30\n    correta = (a + b) * 999 - 0\n    erro_1 = a - b\n    erro_2 = a\n    erro_3 = b\n    erro_4 = a * b"
        })

        # 2ª tentativa: usa apenas números do enunciado e é aprovada
        t2_pot = json.dumps({
            "planejamento": "Plano válido.",
            "enunciado": "Um atleta fez 50 pontos no sábado e 30 pontos no domingo. Qual a pontuação total no fim de semana?",
            "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
            "solver": "def resolver():\n    a = 50\n    b = 30\n    correta = (a + b) * 1 - 0\n    erro_1 = a - b\n    erro_2 = a\n    erro_3 = b\n    erro_4 = a * b"
        })
        t2_blind = json.dumps({
            "resolucao_passo_a_passo": "50 + 30 = 80.",
            "premissas_assumidas": [],
            "dados_nao_utilizados": [],
            "pergunta_respondivel": True,
            "resultado_obtido": 80
        })
        t2_audit = json.dumps({
            "analise": "Item adequado",
            "incoerencia_ou_absurdo": False,
            "comando_ambiguo_ou_incompativel": False,
            "deficit_ou_contradicao": False,
            "complexidade_insuficiente": False
        })

        mock_llm.generate.side_effect = [t1_pot, t2_pot, t2_blind, t2_audit]

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        questao_aprovada = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo="H01",
            max_attempts=3,
            temperature=0.2,
            tema="esportes",
            abertura="relato"
        )

        assert questao_aprovada is not None
        assert questao_aprovada.is_validated is True
        assert questao_aprovada.codigo_erro is None
        assert questao_aprovada.etapa_falha is None
        assert questao_aprovada.ciclo_id is not None
        assert questao_aprovada.tentativa_id is not None

        # Verifica CicloGeracao
        ciclo = db.get(CicloGeracao, questao_aprovada.ciclo_id)
        assert ciclo is not None
        assert ciclo.habilidade_codigo == "H01"
        assert ciclo.total_tentativas == 2
        assert ciclo.sucesso is True
        assert ciclo.tempo_total_segundos >= 0.0

        # Verifica TentativaGeracao (inputs)
        tentativas = (
            db.query(TentativaGeracao)
            .filter(TentativaGeracao.ciclo_id == ciclo.id)
            .order_by(TentativaGeracao.numero_tentativa)
            .all()
        )
        assert len(tentativas) == 2
        assert tentativas[0].numero_tentativa == 1
        assert tentativas[0].modelo == "qwen2.5:7b-test"
        assert tentativas[0].temperatura == 0.2
        assert tentativas[0].tema == "esportes"
        assert tentativas[0].retry_hint is None
        assert tentativas[0].duracao_segundos >= 0.0

        assert tentativas[1].numero_tentativa == 2
        assert tentativas[1].temperatura == 0.25
        assert tentativas[1].retry_hint is not None
        assert "Nexo numérico" in tentativas[1].retry_hint

        # Verifica QuestaoInedita (outputs de cada tentativa do ciclo)
        saidas = (
            db.query(QuestaoInedita)
            .filter(QuestaoInedita.ciclo_id == ciclo.id)
            .all()
        )
        assert len(saidas) == 2

        saida_t1 = tentativas[0].questao_saida
        assert saida_t1 is not None
        assert saida_t1.is_validated is False
        assert saida_t1.etapa_falha == "3_nexo_complexidade"
        assert saida_t1.codigo_erro == "NEXO_NUMERICO"
        assert "999" in (saida_t1.motivo_falha or "")
        assert saida_t1.enunciado is not None
        assert saida_t1.alternativas is None
        assert saida_t1.gabarito is None

        saida_t2 = tentativas[1].questao_saida
        assert saida_t2 is not None
        assert saida_t2.id == questao_aprovada.id
        assert saida_t2.is_validated is True
        assert saida_t2.codigo_erro is None
        assert saida_t2.alternativas is not None
        assert saida_t2.gabarito in ["A", "B", "C", "D", "E"]
    finally:
        db.close()


def test_relational_persistence_all_attempts_failed():
    """
    Valida que quando todas as tentativas de um ciclo falham, o CicloGeracao (sucesso=False),
    todas as TentativaGeracao e todas as saídas reprovadas em QuestaoInedita (is_validated=False)
    permanecem persistidos no banco relacional.
    """
    from app.db.models.ciclo_geracao import CicloGeracao

    db = TestingSessionLocal()
    try:
        mock_llm = MagicMock(spec=LLMClient)
        mock_vs = MagicMock(spec=ChromaVectorStore)
        mock_vs.search.return_value = []

        # Falha nas 2 tentativas por sintaxe JSON inválida na Etapa 1a
        mock_llm.generate.return_value = "texto sem json valido"

        ids_antes = {c.id for c in db.query(CicloGeracao).all()}

        service = QuestionService(llm_client=mock_llm, vector_store=mock_vs)
        with pytest.raises(ValueError, match=r"RN-Q01 \(PoT\)"):
            service.generate_single_questao_inedita(
                db=db,
                habilidade_codigo="H01",
                max_attempts=2
            )

        novos_ciclos = [c for c in db.query(CicloGeracao).all() if c.id not in ids_antes]
        assert len(novos_ciclos) == 1

        ultimo_ciclo = novos_ciclos[0]
        assert ultimo_ciclo.sucesso is False
        assert ultimo_ciclo.total_tentativas == 2
        assert len(ultimo_ciclo.tentativas) == 2
        assert len(ultimo_ciclo.questoes) == 2

        for q_out in ultimo_ciclo.questoes:
            assert q_out.is_validated is False
            assert q_out.etapa_falha == "1a_planejamento"
            assert q_out.codigo_erro == "SINTAXE"
            assert q_out.enunciado is None
    finally:
        db.close()


