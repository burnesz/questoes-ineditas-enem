import os
import logging
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.sanitizer import sanitize_utf8_string, sanitize_metadata

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Serviço de geração de embeddings com intfloat/multilingual-e5-large (1024 dimensões).
    Aplica as diretrizes do modelo E5 (prefixo 'passage:' para documentos e 'query:' para buscas).
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        mock_mode: bool = False
    ):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.device = device or settings.EMBEDDING_DEVICE
        self.mock_mode = mock_mode
        self._model = None

    @property
    def model(self):
        if self._model is None and not self.mock_mode:
            from sentence_transformers import SentenceTransformer
            import torch
            target_device = self.device
            if target_device == "cuda" and not torch.cuda.is_available():
                target_device = "cpu"
            logger.info(f"Carregando modelo de embeddings '{self.model_name}' ({target_device})...")
            self._model = SentenceTransformer(self.model_name, device=target_device)
        return self._model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if self.mock_mode:
            return [[0.01 * (i % 50)] * settings.EMBEDDING_DIMENSION for i in range(len(texts))]

        sanitized_texts = []
        for t in texts:
            clean = sanitize_utf8_string(t)
            sanitized_texts.append(f"passage: {clean}" if clean else "passage: ")

        try:
            embeddings = self.model.encode(sanitized_texts, normalize_embeddings=True, show_progress_bar=False)
            if hasattr(embeddings, "tolist"):
                return embeddings.tolist()
            return embeddings
        except Exception as e:
            logger.warning(f"Erro ao codificar embeddings em lote: {e}. Contingência individual...")
            results = []
            for text_item in sanitized_texts:
                try:
                    emb = self.model.encode([text_item], normalize_embeddings=True, show_progress_bar=False)
                    results.append(emb[0].tolist() if hasattr(emb[0], "tolist") else emb[0])
                except Exception as inner_e:
                    logger.error(f"Texto corrompido ignorado: {inner_e}")
                    results.append([0.0] * settings.EMBEDDING_DIMENSION)
            return results

    def embed_query(self, query: str) -> List[float]:
        if self.mock_mode:
            return [0.01] * settings.EMBEDDING_DIMENSION

        clean_query = sanitize_utf8_string(query)
        prefixed_query = f"query: {clean_query}"
        embedding = self.model.encode(prefixed_query, normalize_embeddings=True, show_progress_bar=False)
        if hasattr(embedding, "tolist"):
            return embedding.tolist()
        return embedding


class ChromaVectorStore:
    """
    Repositório vetorial local embutido usando ChromaDB com persistência em disco.
    Compatível com o fluxo de busca semântica do QuestionService.
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        embedding_service: Optional[EmbeddingService] = None
    ):
        self.persist_directory = persist_directory or settings.CHROMA_PERSIST_DIRECTORY
        self.embedding_service = embedding_service or EmbeddingService()
        self._client = None

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            os.makedirs(self.persist_directory, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_directory)
        return self._client

    def get_or_create_collection(self, name: str = settings.CHROMA_COLLECTION_QUESTOES):
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )

    def upsert_itens(
        self,
        itens: List[Dict[str, Any]],
        collection_name: str = settings.CHROMA_COLLECTION_QUESTOES,
        batch_size: int = 50
    ) -> int:
        """
        Gera embeddings e insere questões históricas no ChromaDB local.
        """
        if not itens:
            return 0

        collection = self.get_or_create_collection(collection_name)
        total = len(itens)
        upserted = 0

        logger.info(f"Upsert de {total} itens na coleção ChromaDB '{collection_name}' (lotes de {batch_size})...")

        for i in range(0, total, batch_size):
            batch = itens[i : i + batch_size]
            texts = [b.get("enunciado", "") for b in batch]
            embeddings = self.embedding_service.embed_documents(texts)

            ids = []
            metadatas = []
            documents = []
            valid_embeddings = []

            for item, emb in zip(batch, embeddings):
                co_item = str(item.get("co_item") or item.get("id"))
                if not co_item:
                    continue

                alts = item.get("alternativas") or {}
                meta = {
                    "co_item": int(item["co_item"]) if item.get("co_item") else 0,
                    "ano": int(item.get("ano", 0)),
                    "habilidade_codigo": str(item.get("habilidade_codigo", "")),
                    "gabarito": str(item.get("gabarito", "")),
                    "alt_a": sanitize_utf8_string(alts.get("A", "")),
                    "alt_b": sanitize_utf8_string(alts.get("B", "")),
                    "alt_c": sanitize_utf8_string(alts.get("C", "")),
                    "alt_d": sanitize_utf8_string(alts.get("D", "")),
                    "alt_e": sanitize_utf8_string(alts.get("E", "")),
                }

                ids.append(co_item)
                metadatas.append(sanitize_metadata(meta))
                documents.append(sanitize_utf8_string(item.get("enunciado", "")))
                valid_embeddings.append(emb)

            if ids:
                collection.upsert(
                    ids=ids,
                    embeddings=valid_embeddings,
                    metadatas=metadatas,
                    documents=documents
                )
                upserted += len(ids)
                logger.info(f"ChromaDB: {upserted}/{total} vetores inseridos.")

        return upserted

    def search(
        self,
        query: str,
        namespace: str = settings.CHROMA_COLLECTION_QUESTOES,
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Executa busca por similaridade de cosseno com filtro de metadados no ChromaDB local.
        Retorna dicionários compatíveis com o formato esperado pelo QuestionService.
        """
        try:
            collection = self.get_or_create_collection(namespace)
            if collection.count() == 0:
                logger.info(f"Coleção ChromaDB '{namespace}' está vazia.")
                return []
        except Exception as e:
            logger.warning(f"Erro ao acessar coleção ChromaDB '{namespace}': {e}")
            return []

        query_vector = self.embedding_service.embed_query(query)

        where_clause = None
        if filter_dict:
            # Converte formato simples de filtro para sintaxe do Chroma
            if len(filter_dict) == 1:
                k, v = next(iter(filter_dict.items()))
                where_clause = {k: {"$eq": v}}
            else:
                where_clause = {"$and": [{k: {"$eq": v}} for k, v in filter_dict.items()]}

        try:
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                where=where_clause,
                include=["metadatas", "documents", "distances"]
            )
        except Exception as e:
            logger.warning(f"Falha na busca vetorial ChromaDB: {e}")
            return []

        formatted = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0]

        for item_id, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
            score = round(max(0.0, 1.0 - float(dist)), 4) if dist is not None else 1.0
            meta_copy = dict(meta or {})
            meta_copy["text"] = doc
            formatted.append({
                "id": str(item_id),
                "score": score,
                "text": doc,
                "metadata": meta_copy
            })

        return formatted
