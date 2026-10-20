"""
Rotas da API FastAPI para Gestão e Geração de Questões do ENEM (Históricas e Inéditas).
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.question_service import QuestionService
from app.schemas.question import (
    QuestaoIneditaResponse,
    QuestaoGenerateRequest
)

router = APIRouter(tags=["Questões"])


def get_question_service() -> QuestionService:
    return QuestionService()


@router.post(
    "/ineditas/gerar",
    response_model=QuestaoIneditaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gera uma questão inédita sob demanda para uma habilidade específica"
)
def gerar_questao_inedita(
    request: QuestaoGenerateRequest,
    db: Session = Depends(get_db),
    service: QuestionService = Depends(get_question_service)
):
    """
    Executa o pipeline RAG/few-shot determinístico no modelo local Qwen 2.5:
    1. Recupera exemplos históricos reais do PostgreSQL para a habilidade informada.
    2. Gera o item formatado como JSON estrito no LLM local.
    3. Valida estruturalmente (ausência de alternativas duplicadas e gabarito único).
    4. Persiste na tabela questoes_ineditas e retorna o registro validado.
    """
    try:
        questao = service.generate_single_questao_inedita(
            db=db,
            habilidade_codigo=request.habilidade_codigo,
            num_few_shot=request.num_few_shot_examples,
            max_attempts=5,
            tema=request.tema,
            abertura=request.abertura
        )
        return questao
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar a geração da questão inédita: {str(e)}"
        )


@router.get(
    "/ineditas",
    response_model=List[QuestaoIneditaResponse],
    summary="Lista questões inéditas cadastradas"
)
def listar_questoes_ineditas(
    habilidade: Optional[str] = Query(None, description="Filtro opcional por código da habilidade (ex: 'H01')"),
    skip: int = Query(0, ge=0, description="Registros a pular"),
    limit: int = Query(50, ge=1, le=100, description="Limite de registros retornados"),
    db: Session = Depends(get_db),
    service: QuestionService = Depends(get_question_service)
):
    """Retorna lista de questões inéditas disponíveis no acervo com suporte a paginação e filtro."""
    return service.list_questoes_ineditas(
        db=db,
        habilidade_codigo=habilidade,
        skip=skip,
        limit=limit
    )


@router.get(
    "/ineditas/{questao_id}",
    response_model=QuestaoIneditaResponse,
    summary="Recupera uma questão inédita específica por UUID"
)
def obter_questao_inedita(
    questao_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: QuestionService = Depends(get_question_service)
):
    """Retorna os detalhes de uma questão inédita pelo identificador UUID."""
    questao = service.get_questao_inedita_by_id(db=db, questao_id=questao_id)
    if not questao:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Questão inédita com ID '{questao_id}' não encontrada."
        )
    return questao
