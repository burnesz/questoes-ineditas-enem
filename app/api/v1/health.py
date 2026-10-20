from typing import Dict, Any
from fastapi import APIRouter, status
from app.core.config import settings
from app.services.llm_client import LLMClient
from app.services.vectorstore import ChromaVectorStore

router = APIRouter(tags=["Health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> Dict[str, Any]:
    """
    Verificação de saúde dos componentes:
    - Status da API FastAPI
    - Status do LLM Ollama local
    - Status do ChromaDB local
    """
    llm_client = LLMClient()
    llm_health = await llm_client.ahealth_check()

    chroma_health = {"status": "unknown", "count": 0}
    try:
        store = ChromaVectorStore()
        coll = store.get_or_create_collection(settings.CHROMA_COLLECTION_QUESTOES)
        chroma_health = {
            "status": "online",
            "persist_directory": settings.CHROMA_PERSIST_DIRECTORY,
            "collection": settings.CHROMA_COLLECTION_QUESTOES,
            "count": coll.count()
        }
    except Exception as e:
        chroma_health = {"status": "error", "message": str(e)}

    overall_status = "ok" if llm_health.get("healthy") else "degraded"

    return {
        "status": overall_status,
        "api": {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "status": "online"
        },
        "llm": llm_health,
        "chromadb": chroma_health
    }
