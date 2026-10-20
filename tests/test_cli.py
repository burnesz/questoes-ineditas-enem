import os
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models
from app.db.base import Base
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.cli import main, create_parser

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(autouse=True)
def setup_cli_test_db(monkeypatch):
    """Substitui a SessionLocal e o engine pelos objetos in-memory durante os testes."""
    monkeypatch.setattr("app.cli.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.cli.engine", test_engine)
    monkeypatch.setattr("app.db.session.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.db.session.engine", test_engine)

    # Popula dados mínimos para teste
    db = TestingSessionLocal()
    try:
        hab = HabilidadeEnem(
            codigo="H01",
            competencia=1,
            descricao="Reconhecer, no contexto social, diferentes significados e representações dos números e operações.",
            eixo_tematico="Números e Operações"
        )
        db.merge(hab)

        q_inedita_id = uuid.UUID("a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")
        q_inedita = db.get(QuestaoInedita, q_inedita_id)
        if not q_inedita:
            q_inedita = QuestaoInedita(
                id=q_inedita_id,
                habilidade_codigo="H01",
                enunciado="Um feirante vende caixas de laranjas contendo 24 unidades cada...",
                alternativas={"A": "24", "B": "48", "C": "72", "D": "96", "E": "120"},
                gabarito="B",
                justificativa="def resolver():\n    correta = 48\n    return {'correta': correta, 'distratores': [24, 72, 96, 120]}",
                is_validated=True
            )
            db.add(q_inedita)
        db.commit()
    finally:
        db.close()


def test_cli_help(capsys):
    ret = main(["--help"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "CLI VERA" in captured
    assert "Subcomandos Disponíveis:" in captured
    assert "generate" in captured
    assert "seed" in captured
    assert "list" in captured
    assert "show" in captured
    assert "stats" in captured
    assert "export" in captured


def test_cli_no_args_shows_help(capsys):
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "CLI VERA" in captured


def test_cli_stats(capsys):
    ret = main(["stats"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "ESTATÍSTICAS E STATUS DO SISTEMA" in captured
    assert "Habilidade" in captured


def test_cli_list(capsys):
    ret = main(["list", "--habilidade", "H01"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d" in captured
    assert "H01" in captured
    assert "B" in captured


def test_cli_list_empty(capsys):
    ret = main(["list", "--habilidade", "H99"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Nenhuma questão inédita encontrada" in captured


def test_cli_show_success(capsys):
    ret = main(["show", "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "QUESTÃO INÉDITA: a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d" in captured
    assert "Habilidade:        H01" in captured
    assert "(B) 48 [GABARITO]" in captured
    assert "JUSTIFICATIVA / CÓDIGO RESOLVER:" in captured


def test_cli_show_json(capsys):
    ret = main(["show", "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d", "--json"])
    assert ret == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["id"] == "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
    assert data["gabarito"] == "B"
    assert data["habilidade_codigo"] == "H01"


def test_cli_show_not_found(capsys):
    fake_id = str(uuid.uuid4())
    ret = main(["show", fake_id])
    assert ret == 1
    captured = capsys.readouterr().out
    assert "não encontrada" in captured


def test_cli_show_invalid_uuid(capsys):
    ret = main(["show", "uuid-invalido-123"])
    assert ret == 1
    captured = capsys.readouterr().out
    assert "ID inválido" in captured


def test_cli_export_json(tmp_path, capsys):
    out_file = tmp_path / "export_test.json"
    ret = main(["export", "-o", str(out_file), "--habilidade", "H01"])
    assert ret == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["habilidade_codigo"] == "H01"


def test_cli_export_markdown(tmp_path, capsys):
    out_file = tmp_path / "export_test.md"
    ret = main(["export", "-o", str(out_file), "--habilidade", "H01"])
    assert ret == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# Caderno de Questões Inéditas" in content
    assert "Habilidade H01" in content
    assert "Gabarito Oficial:" in content


def test_cli_generate_mock(capsys, monkeypatch):
    """Testa geração via mock no CLI."""
    with patch("app.cli.ChromaVectorStore") as mock_vstore_cls:
        mock_vstore = MagicMock()
        mock_vstore.search.return_value = []
        mock_vstore_cls.return_value = mock_vstore

        ret = main(["generate", "--habilidades", "H01", "--count", "1", "--mock", "--non-interactive"])
        assert ret == 0
        captured = capsys.readouterr().out
        assert "RELATÓRIO FINAL DE GERAÇÃO" in captured
        assert "Questões Geradas com Sucesso: 1" in captured
