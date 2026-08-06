"""RAG knowledge agent backed by embeddings, Qdrant, and PostgreSQL."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.logging import configure_logging
from src.database.models import Document
from src.database.repository import DocumentRepository

logger = configure_logging(get_settings().AEGIS_DEBUG)

VECTOR_SIZE = 768
_MEMORY_COLLECTIONS: dict[str, list[dict[str, Any]]] = {}


class AsyncVectorStore:
    """Async-compatible vector store with Qdrant and in-memory fallback."""

    def __init__(self, collection_name: str, vector_size: int = VECTOR_SIZE) -> None:
        """Initialize Qdrant client when available."""

        self.collection_name = collection_name
        self.vector_size = vector_size
        self.settings = get_settings()
        self.client: Any | None = None
        try:
            from qdrant_client import AsyncQdrantClient

            self.client = AsyncQdrantClient(url=self.settings.AEGIS_QDRANT_URL, timeout=1.0, check_compatibility=False)
        except Exception as exc:
            logger.warning("qdrant_client_unavailable", error=str(exc))

    async def ensure_collection(self) -> None:
        """Ensure the vector collection exists."""

        if self.client is None:
            _MEMORY_COLLECTIONS.setdefault(self.collection_name, [])
            return
        try:
            from qdrant_client.http.models import Distance, VectorParams

            collections = await self.client.get_collections()
            names = {collection.name for collection in collections.collections}
            if self.collection_name not in names:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
        except Exception as exc:
            logger.warning("qdrant_collection_fallback", error=str(exc))
            self.client = None
            _MEMORY_COLLECTIONS.setdefault(self.collection_name, [])

    async def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        """Upsert one vector point."""

        await self.ensure_collection()
        if self.client is None:
            collection = _MEMORY_COLLECTIONS.setdefault(self.collection_name, [])
            collection[:] = [point for point in collection if point["id"] != point_id]
            collection.append({"id": point_id, "vector": vector, "payload": payload})
            return
        try:
            from qdrant_client.http.models import PointStruct

            await self.client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(id=point_id, vector=vector, payload=payload)],
            )
        except Exception as exc:
            logger.warning("qdrant_upsert_fallback", error=str(exc))
            self.client = None
            await self.upsert(point_id, vector, payload)

    async def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """Search for nearest vectors."""

        await self.ensure_collection()
        if self.client is None:
            results = []
            for point in _MEMORY_COLLECTIONS.get(self.collection_name, []):
                results.append(
                    {
                        "id": point["id"],
                        "score": self._cosine(vector, point["vector"]),
                        "payload": point["payload"],
                    }
                )
            return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]
        try:
            hits = await self.client.search(collection_name=self.collection_name, query_vector=vector, limit=limit)
            return [{"id": str(hit.id), "score": float(hit.score), "payload": hit.payload or {}} for hit in hits]
        except Exception as exc:
            logger.warning("qdrant_search_fallback", error=str(exc))
            self.client = None
            return await self.search(vector, limit)

    async def collection_exists(self) -> bool:
        """Return whether the collection exists in the active store."""

        await self.ensure_collection()
        if self.client is None:
            return self.collection_name in _MEMORY_COLLECTIONS
        try:
            collections = await self.client.get_collections()
            return any(collection.name == self.collection_name for collection in collections.collections)
        except Exception as exc:
            logger.warning("qdrant_exists_fallback", error=str(exc))
            self.client = None
            return await self.collection_exists()

    def _cosine(self, left: list[float], right: list[float]) -> float:
        """Calculate cosine similarity."""

        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)


class RAGKnowledgeAgent(BaseAgent):
    """Maintain and query the Aegis AI vector knowledge base."""

    def __init__(self, name: str, llm_client: Any, db_repo: Any, storage_adapter: Any) -> None:
        """Initialize RAG dependencies."""

        super().__init__(name, llm_client, db_repo, storage_adapter)
        settings = get_settings()
        self.vector_store = AsyncVectorStore(settings.AEGIS_QDRANT_COLLECTION)

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ingest or query mode."""

        try:
            action = context.get("action")
            if action == "ingest":
                return await self._ingest(context)
            if action == "query":
                return await self._query(context)
            return {"rag_failed": True, "error": "Unsupported RAG action."}
        except Exception as exc:
            logger.error("rag_agent_failed", error=str(exc))
            return {"rag_failed": True, "error": "Unable to complete knowledge operation."}

    async def _ingest(self, context: dict[str, Any]) -> dict[str, Any]:
        """Embed and persist a knowledge document."""

        embedding = await self._embed_text(context["content"])
        document_id = context.get("document_id", "")
        if isinstance(self.db_repo, AsyncSession):
            document = await DocumentRepository(self.db_repo).create(
                Document(
                    doc_type=context["doc_type"],
                    title=context.get("title") or context["doc_type"],
                    content=context["content"],
                    embedding_vector={"model": get_settings().AEGIS_EMBEDDING_MODEL, "vector": embedding},
                    metadata_json=context.get("metadata", {}),
                    source_url=context.get("source_url"),
                )
            )
            document_id = document.id
        if not document_id:
            document_id = hashlib.sha256(context["content"].encode()).hexdigest()[:32]
        await self.vector_store.upsert(
            document_id,
            embedding,
            {"document_id": document_id, "doc_type": context["doc_type"], "title": context.get("title") or context["doc_type"]},
        )
        await self.log_decision("KNOWLEDGE_INGESTED", f"Ingested {context['doc_type']} knowledge", 0.9)
        return {"document_id": document_id, "embedding_dimension": len(embedding), "collection": get_settings().AEGIS_QDRANT_COLLECTION}

    async def _query(self, context: dict[str, Any]) -> dict[str, Any]:
        """Retrieve relevant documents and answer a natural-language question."""

        embedding = await self._embed_text(context["question"])
        hits = await self.vector_store.search(embedding, limit=5)
        documents: list[Document] = []
        scores: dict[str, float] = {}
        if isinstance(self.db_repo, AsyncSession):
            repo = DocumentRepository(self.db_repo)
            for hit in hits:
                doc_id = hit.get("payload", {}).get("document_id")
                if doc_id:
                    document = await repo.get_by_id(doc_id)
                    if document is not None:
                        documents.append(document)
                        scores[document.id] = float(hit.get("score", 0.0))
            if not documents:
                documents = list(await repo.search_content(context["question"], limit=5))
        context_text = "\n\n".join(f"[{doc.doc_type}] {doc.title or ''}: {doc.content}" for doc in documents)
        prompt = f"Based on this context: {context_text}, answer: {context['question']}"
        try:
            answer = await self.llm.generate(prompt, expect_json=False)
        except Exception as exc:
            logger.warning("rag_answer_fallback", error=str(exc))
            answer = context_text[:500] if context_text else "No matching knowledge was found."
        sources = [
            {"doc_type": doc.doc_type, "title": doc.title, "score": float(scores.get(doc.id, 0.0))}
            for doc in documents
        ]
        confidence = max([source["score"] for source in sources], default=0.5)
        return {"answer": answer, "sources": sources, "confidence": float(confidence)}

    async def _embed_text(self, text: str) -> list[float]:
        """Generate a 768-dimensional embedding, falling back only if Ollama is unavailable."""

        try:
            embedding = await self.llm.embed(text, model=get_settings().AEGIS_EMBEDDING_MODEL)
            if len(embedding) == VECTOR_SIZE:
                return embedding
            if len(embedding) > VECTOR_SIZE:
                return embedding[:VECTOR_SIZE]
            return embedding + [0.0] * (VECTOR_SIZE - len(embedding))
        except Exception as exc:
            logger.warning("embedding_fallback", error=str(exc))
            return self._deterministic_embedding(text)

    def _deterministic_embedding(self, text: str) -> list[float]:
        """Create a stable local embedding when the external embedding service is unreachable."""

        digest = hashlib.sha256(text.encode()).digest()
        values = []
        for index in range(VECTOR_SIZE):
            byte = digest[index % len(digest)]
            values.append((byte / 255.0) - 0.5)
        return values


async def ingest_pipeline_completion(session: AsyncSession, pipeline_id: str, payload: dict[str, Any]) -> None:
    """Auto-ingest completed pipeline context into the knowledge base."""

    agent = RAGKnowledgeAgent("rag", _NoopLLM(), session, None)
    await agent.execute(
        {
            "action": "ingest",
            "doc_type": "pipeline_log",
            "content": str(payload),
            "metadata": {"pipeline_id": pipeline_id, "event": "pipeline_completed"},
            "title": f"Pipeline {pipeline_id} completion",
        }
    )


async def ingest_alert(session: AsyncSession, alert_payload: dict[str, Any]) -> None:
    """Auto-ingest alert details into the knowledge base."""

    agent = RAGKnowledgeAgent("rag", _NoopLLM(), session, None)
    await agent.execute(
        {
            "action": "ingest",
            "doc_type": "incident",
            "content": str(alert_payload),
            "metadata": {"event": "alert"},
            "title": "Monitoring alert",
        }
    )


async def ingest_human_decision(session: AsyncSession, pipeline_id: str, decision: dict[str, Any]) -> None:
    """Auto-ingest human approval or rejection decisions."""

    agent = RAGKnowledgeAgent("rag", _NoopLLM(), session, None)
    await agent.execute(
        {
            "action": "ingest",
            "doc_type": "manual",
            "content": str(decision),
            "metadata": {"pipeline_id": pipeline_id, "event": "human_decision"},
            "title": f"Human decision for {pipeline_id}",
        }
    )


class _NoopLLM:
    """Internal LLM fallback for automatic background ingestion helpers."""

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        return RAGKnowledgeAgent("rag", self, None, None)._deterministic_embedding(text)

    async def generate(self, prompt: str, expect_json: bool = False, **kwargs: Any) -> str:
        return prompt
