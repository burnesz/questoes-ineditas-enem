import pytest
import json
import uuid
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models
from app.db.base import Base
from app.db.session import get_db
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.main import app
from app.api.v1.questoes import get_question_service
from app.services.llm_client import LLMClient
from app.services.question_service import QuestionService

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_api_data():
    prev_get_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    try:
        hab = HabilidadeEnem(
            codigo="H02",
            competencia=1,
            descricao="Identificar padrões numéricos ou princípios de contagem.",
            eixo_tematico="Números e Operações"
        )
        db.merge(hab)

        # Questão ENEM para few-shot
        q_enem = db.query(QuestaoEnem).filter(QuestaoEnem.habilidade_codigo == "H02").first()
        if not q_enem:
            q_enem = QuestaoEnem(
                id=uuid.uuid4(),
                ano=2020,
                habilidade_codigo="H02",
                enunciado="Uma senha de 4 dígitos deve ser formada usando apenas os algarismos 1, 2, 3, 4 sem repetição.",
                alternativas={"A": "12", "B": "16", "C": "24", "D": "32", "E": "48"},
                gabarito="C"
            )
            db.add(q_enem)

        # Questão Inédita pré-existente
        q_inedita = db.query(QuestaoInedita).filter(QuestaoInedita.habilidade_codigo == "H02").first()
        if not q_inedita:
            q_inedita = QuestaoInedita(
                id=uuid.uuid4(),
                habilidade_codigo="H02",
                enunciado="Quantos números pares de 3 algarismos distintos podem ser formados com os algarismos de 1 a 9?",
                alternativas={"A": "224", "B": "256", "C": "288", "D": "312", "E": "336"},
                gabarito="A",
                justificativa="Cálculo combinatório...",
                is_validated=True
            )
            db.add(q_inedita)
        db.commit()
    finally:
        db.close()

    yield
    if prev_get_db is not None:
        app.dependency_overrides[get_db] = prev_get_db
    else:
        app.dependency_overrides.pop(get_db, None)


def test_api_listar_questoes_ineditas():
    response = client.get("/api/v1/questoes/ineditas?habilidade=H02")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["habilidade_codigo"] == "H02"
    assert "alternativas" in data[0]


def test_api_obter_questao_inedita():
    # Primeiro busca a lista
    list_resp = client.get("/api/v1/questoes/ineditas?habilidade=H02")
    item_id = list_resp.json()[0]["id"]

    response = client.get(f"/api/v1/questoes/ineditas/{item_id}")
    assert response.status_code == 200
    item = response.json()
    assert item["id"] == item_id
    assert item["habilidade_codigo"] == "H02"


def test_api_obter_questao_inedita_not_found():
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/questoes/ineditas/{fake_id}")
    assert response.status_code == 404


def test_api_gerar_questao_inedita():
    mock_llm = MagicMock(spec=LLMClient)
    resp_fase1 = json.dumps({
        "enunciado": "Quantas maneiras distintas existem de organizar 5 livros diferentes em uma prateleira linear?",
        "solver": "def resolver():\n    import math\n    n = 5\n    val = math.factorial(n - 0) * 1\n    return {'correta': val, 'distratores': [60, 90, 150, 180]}"
    })
    resp_blind = json.dumps({
        "resolucao_passo_a_passo": "Permutação simples de 5 elementos: 5! = 120 maneiras.",
        "resultado_obtido": "120"
    })
    resp_equiv = json.dumps({
        "equivalentes": True,
        "explicacao_equivalencia": "120 e 120 são matematicamente equivalentes."
    })
    resp_audit = json.dumps({
        "possui_incoerencia": False,
        "possui_ambiguidade": False,
        "deficit_informacoes": False,
        "erros_ou_vazamentos": False,
        "duplicacao_tabelas": False
    })
    mock_llm.generate.side_effect = [resp_fase1, resp_blind, resp_equiv, resp_audit]

    def override_question_service():
        mock_vs = MagicMock()
        mock_vs.search.return_value = []
        return QuestionService(llm_client=mock_llm, vector_store=mock_vs)

    app.dependency_overrides[get_question_service] = override_question_service

    payload = {
        "habilidade_codigo": "H02",
        "num_few_shot_examples": 1
    }
    response = client.post("/api/v1/questoes/ineditas/gerar", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["habilidade_codigo"] == "H02"
    assert created["is_validated"] is True
    assert created["alternativas"][created["gabarito"]] == "120"

    # Limpa override após o teste
    app.dependency_overrides.pop(get_question_service, None)
