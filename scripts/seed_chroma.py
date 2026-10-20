import os
import sys
import logging
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.vectorstore import ChromaVectorStore, EmbeddingService
from scripts.seed_questoes import parse_csv_rows

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_chroma")


def seed_chroma(
    csv_path: str = "data/itens_prova_2009_2024_enriquecido.csv",
    batch_size: int = 50,
    mock_embeddings: bool = False
):
    logger.info("=" * 70)
    logger.info(" SEED DO BANCO VETORIAL LOCAL CHROMADB (ENEM 2009-2024)")
    logger.info("=" * 70)

    items = parse_csv_rows(csv_path)
    logger.info(f"Carregadas {len(items)} questões do CSV '{csv_path}'.")

    emb_service = EmbeddingService(mock_mode=mock_embeddings)
    store = ChromaVectorStore(embedding_service=emb_service)

    total_upserted = store.upsert_itens(items, batch_size=batch_size)
    logger.info(f"Concluído: {total_upserted} questões indexadas com sucesso no ChromaDB.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexação do acervo histórico do ENEM no ChromaDB local.")
    parser.add_argument("--csv", default="data/itens_prova_2009_2024_enriquecido.csv", help="Caminho do CSV")
    parser.add_argument("--batch-size", type=int, default=50, help="Tamanho do lote para embeddings")
    parser.add_argument("--mock-embeddings", action="store_true", help="Gera vetores mock sem carregar modelo neural (testes rápidos)")
    args = parser.parse_args()

    seed_chroma(
        csv_path=args.csv,
        batch_size=args.batch_size,
        mock_embeddings=args.mock_embeddings
    )
