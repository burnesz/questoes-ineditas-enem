"""Testes da API HTTP (app/api.py), sem Ollama, embeddings nem banco: a geração de cada pedido é substituída."""
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api as api


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(api, "lotes", api.Lotes())
    monkeypatch.setattr(api, "SessionLocal", MagicMock())
    monkeypatch.setattr(api, "init_db", lambda db: None)
    monkeypatch.setattr(api, "_servicos", lambda: (None, None))
    monkeypatch.setattr(api.settings, "API_KEY", None)
    return TestClient(api.app)


def _gerar_falso(aprovar=lambda hab: True, espera=0.0):
    def gerar_uma(db, gerador, avaliador, habilidade, max_tentativas, ao_tentar):
        ao_tentar(1)
        time.sleep(espera)
        if not aprovar(habilidade):
            ao_tentar(max_tentativas)
            return None
        return {"id": f"id-{habilidade}-{time.time_ns()}", "habilidade_codigo": habilidade, "enunciado": "Quanto?",
                "alternativas": {l: str(i) for i, l in enumerate("ABCDE")}, "gabarito": "A",
                "justificativa": "Porque sim.", "thought_scratchpad": None}
    return gerar_uma


def _esperar(cliente, lote_id, limite=5.0):
    fim = time.time() + limite
    while time.time() < fim:
        dados = cliente.get(f"/lotes/{lote_id}").json()
        if dados["status"] != "em_andamento":
            return dados
        time.sleep(0.02)
    raise AssertionError("lote não terminou")


def test_habilidades_sem_desabilitadas(cliente):
    codigos = [h["codigo"] for h in cliente.get("/habilidades").json()]
    assert len(codigos) == 28 and "H06" not in codigos and "H20" not in codigos


def test_lote_de_duas_habilidades_com_duas_questoes(cliente, monkeypatch):
    monkeypatch.setattr(api, "gerar_uma", _gerar_falso(aprovar=lambda h: h == "H01"))
    r = cliente.post("/lotes", json={"habilidades": ["h1", "5"], "quantidade": 2})
    assert r.status_code == 202 and r.json()["total"] == 4
    dados = _esperar(cliente, r.json()["id"])
    assert dados["status"] == "concluido" and dados["feitos"] == 4 and dados["aprovadas"] == 2
    assert [p["habilidade"] for p in dados["pedidos"]] == ["H01", "H05", "H01", "H05"]
    aprovada = next(p for p in dados["pedidos"] if p["status"] == "aprovada")
    assert set(aprovada["questao"]) >= {"id", "enunciado", "alternativas", "gabarito", "justificativa"}
    reprovada = next(p for p in dados["pedidos"] if p["status"] == "reprovada")
    assert reprovada["questao"] is None and reprovada["tentativas"] == 5


def test_all_usa_as_28_ativas(cliente, monkeypatch):
    monkeypatch.setattr(api, "gerar_uma", _gerar_falso())
    r = cliente.post("/lotes", json={"habilidades": "all"})
    assert r.json()["total"] == 28
    _esperar(cliente, r.json()["id"])


def test_habilidade_desabilitada_ou_inexistente(cliente):
    assert cliente.post("/lotes", json={"habilidades": ["H06"]}).status_code == 422
    assert cliente.post("/lotes", json={"habilidades": ["H01", "H20"]}).status_code == 422
    assert cliente.post("/lotes", json={"habilidades": ["H31"]}).status_code == 422
    assert cliente.post("/lotes", json={"habilidades": []}).status_code == 422


def test_um_lote_por_vez_e_cancelamento(cliente, monkeypatch):
    monkeypatch.setattr(api, "gerar_uma", _gerar_falso(espera=0.2))
    lote_id = cliente.post("/lotes", json={"habilidades": ["H01", "H02", "H03"]}).json()["id"]
    assert cliente.post("/lotes", json={"habilidades": ["H04"]}).status_code == 409
    cliente.post(f"/lotes/{lote_id}/cancelar")
    dados = _esperar(cliente, lote_id)
    assert dados["status"] == "cancelado" and dados["feitos"] < 3
    assert any(p["status"] == "nao_gerado" for p in dados["pedidos"])
    assert cliente.post("/lotes", json={"habilidades": ["H04"]}).status_code == 202


def test_lote_inexistente(cliente):
    assert cliente.get("/lotes/nao-existe").status_code == 404


def test_chave_de_api(cliente, monkeypatch):
    monkeypatch.setattr(api.settings, "API_KEY", "segredo")
    assert cliente.get("/habilidades").status_code == 401
    assert cliente.get("/habilidades", headers={"X-API-Key": "segredo"}).status_code == 200


def test_queda_do_ollama_interrompe_o_lote(cliente, monkeypatch):
    def cai(*a, **k):
        raise api.LLMConnectionError("Ollama fora do ar")
    monkeypatch.setattr(api, "gerar_uma", cai)
    lote_id = cliente.post("/lotes", json={"habilidades": ["H01", "H02"]}).json()["id"]
    dados = _esperar(cliente, lote_id)
    assert dados["status"] == "erro" and "Ollama" in dados["erro"]
