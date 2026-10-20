from fastapi import APIRouter
from app.api.v1 import health, questoes

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(questoes.router, prefix="/questoes", tags=["Questões"])
