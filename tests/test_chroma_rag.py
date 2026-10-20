import pytest
import uuid
import shutil
import os
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.services.vectorstore import ChromaVectorStore, EmbeddingService
from app.services.question_service import QuestionService
from app.services.llm_client import LLMClient

TEST_CHROMA_DIR = "./test_chroma_data"

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(scope="module", autouse=True)
def setup_db_and_chroma():
    # Setup DB
    db = TestingSessionLocal()
    hab = HabilidadeEnem(
        codigo="H01",
        competencia=1,
        descricao="Reconhecer representações dos números e operações.",
        eixo_tematico="Números e Operações"
    )
    db.merge(hab)

    q = QuestaoEnem(
        id=uuid.uuid4(),
        co_item=1001,
        ano=2022,
        habilidade_codigo="H01",
        enunciado="Questão relacional histórica de exemplo para teste H01.",
        alternativas={"A": "10", "B": "20", "C": "30", "D": "40", "E": "50"},
        gabarito="B"
    )
    db.add(q)
    db.commit()
    db.close()

    yield

    if os.path.exists(TEST_CHROMA_DIR):
        shutil.rmtree(TEST_CHROMA_DIR, ignore_errors=True)


def test_embedding_service_mock():
    emb = EmbeddingService(mock_mode=True)
    doc_vecs = emb.embed_documents(["Enunciado de teste 1", "Enunciado de teste 2"])
    assert len(doc_vecs) == 2
    assert len(doc_vecs[0]) == 1024

    q_vec = emb.embed_query("Busca de teste")
    assert len(q_vec) == 1024


def test_chroma_vectorstore_upsert_and_search():
    emb = EmbeddingService(mock_mode=True)
    store = ChromaVectorStore(persist_directory=TEST_CHROMA_DIR, embedding_service=emb)

    itens = [
        {
            "co_item": 9991,
            "ano": 2021,
            "habilidade_codigo": "H01",
            "enunciado": "Um motorista percorre 120 km em 2 horas. Qual a velocidade média?",
            "alternativas": {"A": "50", "B": "60", "C": "70", "D": "80", "E": "90"},
            "gabarito": "B"
        },
        {
            "co_item": 9992,
            "ano": 2022,
            "habilidade_codigo": "H02",
            "enunciado": "Quantos números pares existem de 1 a 20?",
            "alternativas": {"A": "5", "B": "10", "C": "15", "D": "20", "E": "25"},
            "gabarito": "B"
        }
    ]

    upserted = store.upsert_itens(itens, collection_name="test_questoes")
    assert upserted == 2

    # Busca com filtro por habilidade H01
    results_h01 = store.search(
        query="velocidade média percorrida",
        namespace="test_questoes",
        top_k=5,
        filter_dict={"habilidade_codigo": "H01"}
    )
    assert len(results_h01) == 1
    assert results_h01[0]["metadata"]["habilidade_codigo"] == "H01"
    assert results_h01[0]["metadata"]["gabarito"] == "B"
    assert "score" in results_h01[0]


def test_question_service_rag_with_chroma_and_fallback():
    db = TestingSessionLocal()
    emb = EmbeddingService(mock_mode=True)
    store = ChromaVectorStore(persist_directory=TEST_CHROMA_DIR, embedding_service=emb)

    # 1. Busca com Chroma contendo dados
    service = QuestionService(llm_client=LLMClient(mock_mode=True), vector_store=store)
    examples = service.retrieve_rag_few_shot_examples(
        habilidade_codigo="H01",
        k=2,
        db=db
    )
    assert isinstance(examples, list)
    # Se chroma retornar, deve ter o item; se falhar, retorna do db relacional
    assert len(examples) >= 1
    assert "enunciado" in examples[0]
    assert "alternativas" in examples[0]

    # 2. Busca para habilidade sem itens no Chroma -> aciona fallback relacional no SQLite
    fallback_examples = service.retrieve_rag_few_shot_examples(
        habilidade_codigo="H99",  # inexistente
        k=2,
        db=db
    )
    assert isinstance(fallback_examples, list)
