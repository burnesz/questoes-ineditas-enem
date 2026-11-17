"""
API HTTP mínima do gerador de questões inéditas, consumida pela plataforma VERA.

Gera em lote, como `cli.py generate --habilidades ... --count ...`, com o fluxo do Experimento 2: cada tentativa
passa pelas Etapas 1 a 3 com o gerador (MODELO_GERADOR) e pela Etapa 4 com o avaliador (MODELO_AVALIADOR); o
pedido para na primeira questão aprovada ou em max_tentativas. Um lote leva minutos ou horas, então roda numa
thread: POST /lotes devolve o id, e GET /lotes/{id} mostra o andamento. Um lote por vez (a GPU é uma só).

Subir:  ./.venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8100
"""
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.schemas.question import HABILIDADES_DESABILITADAS, resolver_habilidades
from app.services.llm_client import LLMClient, LLMConnectionError, LLMTimeoutError
from app.services.question_service import QuestionService
from app.services.vectorstore import ChromaVectorStore, EmbeddingService

logger = logging.getLogger("questoes_ineditas.api")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARQ_HABILIDADES = os.path.join(RAIZ, "data", "habilidades_queries.json")


def exigir_chave(x_api_key: Optional[str] = Header(default=None)) -> None:
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida.")


app = FastAPI(title="Questões inéditas ENEM", version=settings.VERSION, dependencies=[Depends(exigir_chave)])


class LoteRequest(BaseModel):
    habilidades: Union[Literal["all"], List[str]] = Field(..., description="'all' ou lista, ex.: ['H01', 'H05']")
    quantidade: int = Field(1, ge=1, le=10, description="Questões por habilidade")
    max_tentativas: int = Field(5, ge=1, le=10, description="Tentativas por questão (geração + avaliação)")


# ---------------------------------------------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------------------------------------------

def _servicos():
    """Gerador e avaliador com o mesmo banco vetorial (como no Experimento 2)."""
    vs = ChromaVectorStore(embedding_service=EmbeddingService(mock_mode=settings.API_MOCK))
    gerador = QuestionService(llm_client=LLMClient(model_name=settings.MODELO_GERADOR, mock_mode=settings.API_MOCK),
                              vector_store=vs)
    avaliador = QuestionService(llm_client=LLMClient(model_name=settings.MODELO_AVALIADOR,
                                                     think=settings.AVALIADOR_THINK, mock_mode=settings.API_MOCK),
                                vector_store=vs)
    return gerador, avaliador


def _questao_dict(q) -> Dict[str, Any]:
    return {"id": str(q.id), "habilidade_codigo": q.habilidade_codigo, "enunciado": q.enunciado,
            "alternativas": q.alternativas, "gabarito": q.gabarito, "justificativa": q.justificativa,
            "thought_scratchpad": q.thought_scratchpad}


def gerar_uma(db, gerador, avaliador, habilidade: str, max_tentativas: int, ao_tentar: Callable[[int], None]):
    """Tenta até max_tentativas vezes; devolve a questão aprovada (dict) ou None."""
    for tentativa in range(1, max_tentativas + 1):
        ao_tentar(tentativa)
        try:
            questao = gerador.generate_single_questao_inedita(db=db, habilidade_codigo=habilidade, max_attempts=1,
                                                              ate_etapa3=True)
        except (LLMConnectionError, LLMTimeoutError):
            db.rollback()
            raise  # Ollama fora do ar: interrompe o lote, em vez de contar como reprovação
        except Exception as e:  # reprovada nas Etapas 2 ou 3 (o serviço já gravou a tentativa)
            db.rollback()
            logger.info("%s tentativa %d: reprovada antes da Etapa 4 (%s)", habilidade, tentativa, str(e)[:120])
            continue
        if avaliador.avaliar_questao_pendente(db, questao).aprovada:
            return _questao_dict(questao)
    return None


class Lotes:
    """Estado dos lotes em memória; um lote por vez."""

    def __init__(self):
        self.trava = threading.Lock()
        self.lotes: Dict[str, Dict[str, Any]] = {}

    def em_andamento(self) -> Optional[str]:
        return next((i for i, l in self.lotes.items() if l["status"] == "em_andamento"), None)

    def criar(self, habilidades: List[str], quantidade: int, max_tentativas: int) -> Dict[str, Any]:
        with self.trava:
            if self.em_andamento():
                raise HTTPException(status_code=409, detail="Já há um lote em andamento.")
            lote_id = str(uuid.uuid4())
            pedidos = [{"n": n, "habilidade": h, "status": "aguardando", "tentativas": 0, "questao": None}
                       for n, h in enumerate([h for _ in range(quantidade) for h in habilidades], start=1)]
            self.lotes[lote_id] = {"id": lote_id, "status": "em_andamento", "criado_em": time.time(),
                                   "max_tentativas": max_tentativas, "cancelar": False, "erro": None,
                                   "pedidos": pedidos}
        threading.Thread(target=self._executar, args=(lote_id,), daemon=True).start()
        return self.lotes[lote_id]

    def _executar(self, lote_id: str) -> None:
        lote = self.lotes[lote_id]
        db = SessionLocal()
        try:
            init_db(db)
            gerador, avaliador = _servicos()
            for pedido in lote["pedidos"]:
                if lote["cancelar"]:
                    break
                pedido["status"] = "gerando"
                questao = gerar_uma(db, gerador, avaliador, pedido["habilidade"], lote["max_tentativas"],
                                    lambda t, p=pedido: p.__setitem__("tentativas", t))
                pedido["questao"] = questao
                pedido["status"] = "aprovada" if questao else "reprovada"
            lote["status"] = "cancelado" if lote["cancelar"] else "concluido"
        except Exception as e:
            logger.exception("Lote %s interrompido", lote_id)
            lote.update(status="erro", erro=f"{type(e).__name__}: {e}"[:300])
        finally:
            for p in lote["pedidos"]:
                if p["status"] in ("aguardando", "gerando"):
                    p["status"] = "nao_gerado"
            db.close()

    def publico(self, lote_id: str) -> Dict[str, Any]:
        lote = self.lotes.get(lote_id)
        if not lote:
            raise HTTPException(status_code=404, detail="Lote não encontrado.")
        feitos = sum(1 for p in lote["pedidos"] if p["status"] in ("aprovada", "reprovada"))
        return {"id": lote["id"], "status": lote["status"], "erro": lote["erro"],
                "max_tentativas": lote["max_tentativas"], "total": len(lote["pedidos"]), "feitos": feitos,
                "aprovadas": sum(1 for p in lote["pedidos"] if p["status"] == "aprovada"),
                "pedidos": [{k: p[k] for k in ("n", "habilidade", "status", "tentativas", "questao")}
                            for p in lote["pedidos"]]}


lotes = Lotes()


# ---------------------------------------------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    if settings.API_MOCK:
        return {"ok": True, "mock": True, "gerador": settings.MODELO_GERADOR, "avaliador": settings.MODELO_AVALIADOR}
    estado = LLMClient(model_name=settings.MODELO_GERADOR).health_check()
    return {"ok": bool(estado.get("healthy")), "mock": False, "gerador": settings.MODELO_GERADOR,
            "avaliador": settings.MODELO_AVALIADOR, "modelos_disponiveis": estado.get("available_models")}


@app.get("/habilidades")
def habilidades() -> List[Dict[str, str]]:
    with open(ARQ_HABILIDADES, encoding="utf-8") as f:
        dados = json.load(f)
    return [{"codigo": h["habilidade_codigo"], "descricao": h["descricao_original"]}
            for h in dados if h["habilidade_codigo"] not in HABILIDADES_DESABILITADAS]


@app.post("/lotes", status_code=202)
def criar_lote(req: LoteRequest) -> Dict[str, Any]:
    ativas, desabilitadas = resolver_habilidades(req.habilidades)
    validas = {f"H{i:02d}" for i in range(1, 31)}
    invalidas = [h for h in ativas if h not in validas]
    if invalidas:
        raise HTTPException(status_code=422, detail=f"Habilidades inexistentes: {', '.join(invalidas)}.")
    if desabilitadas:
        raise HTTPException(status_code=422, detail=f"Geração desabilitada para {', '.join(desabilitadas)} "
                                                    "(dependem de interpretação visual).")
    if not ativas:
        raise HTTPException(status_code=422, detail="Nenhuma habilidade informada.")
    lote = lotes.criar(ativas, req.quantidade, req.max_tentativas)
    return {"id": lote["id"], "total": len(lote["pedidos"])}


@app.get("/lotes/{lote_id}")
def consultar_lote(lote_id: str) -> Dict[str, Any]:
    return lotes.publico(lote_id)


@app.post("/lotes/{lote_id}/cancelar")
def cancelar_lote(lote_id: str) -> Dict[str, Any]:
    if lote_id not in lotes.lotes:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    lotes.lotes[lote_id]["cancelar"] = True
    return lotes.publico(lote_id)
