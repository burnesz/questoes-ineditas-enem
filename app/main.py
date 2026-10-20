import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.router import api_router
from app.db.session import SessionLocal, get_db
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("questoes_ineditas.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando Gerador de Questões Inéditas ENEM...")
    try:
        if get_db in app.dependency_overrides:
            db_gen = app.dependency_overrides[get_db]()
            db = next(db_gen)
            try:
                init_db(db)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        else:
            db = SessionLocal()
            try:
                init_db(db)
            finally:
                db.close()
    except Exception as e:
        logger.warning(f"Aviso ao inicializar banco de dados: {e}")

    yield

    logger.info("Encerrando Gerador de Questões Inéditas ENEM...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API para Geração e Validação de Questões Inéditas de Matemática no contexto do ENEM (PoT + 3 Etapas).",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)
