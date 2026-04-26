"""
MAIHERA Brain Layer — ChromaDB Vector Store
Manages semantic memory and similarity search
across all brain nodes using local embeddings.
"""

import os
import logging
import threading
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
COLLECTION_NAME = 'maihera_nodes'
EMBEDDING_FLOOR = 0.05


class VectorStore:
    """
    Semantic memory layer for MAIHERA.
    Embeds node descriptions locally using sentence-transformers.
    Provides similarity search across the full brain graph.
    ChromaDB is not thread-safe for writes — all write
    operations use a threading lock.
    """

    def __init__(self, persist_dir: Optional[str] = None):
        raw = persist_dir or os.getenv(
            'CHROMA_PERSIST_DIR', './chroma_data'
        )
        self.persist_dir = Path(__file__).parent.parent / raw
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection = None
        self._model: Optional[SentenceTransformer] = None

    def initialize(self) -> None:
        """
        Load the embedding model and connect to ChromaDB.
        Must be called before any other method.
        """
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        self._model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Embedding model loaded.")

        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        count = self._collection.count()
        logger.info(
            "ChromaDB collection '%s' ready. Documents: %d",
            COLLECTION_NAME, count
        )

    def _embed(self, text: str) -> list[float]:
        """Generate embedding for a text string."""
        if not self._model:
            raise RuntimeError(
                "VectorStore not initialized. Call initialize() first."
            )
        return self._model.encode(text).tolist()

    def upsert_node(
        self,
        node_id: str,
        description: str,
        metadata: dict
    ) -> None:
        """
        Embed a node description and upsert into ChromaDB.
        Uses the node_id as the ChromaDB document ID — same ID
        as Neo4j for direct cross-store lookup.
        Metadata must include: type, project_id, status, label.
        Thread-safe via write lock.
        """
        if not description or not description.strip():
            description = metadata.get('label', node_id)

        embedding = self._embed(description)

        clean_metadata = {
            'type': str(metadata.get('type', 'unknown')),
            'project_id': str(metadata.get('project_id', '')),
            'status': str(metadata.get('status', 'active')),
            'label': str(metadata.get('label', '')),
        }

        with self._write_lock:
            self._collection.upsert(
                ids=[node_id],
                embeddings=[embedding],
                documents=[description],
                metadatas=[clean_metadata]
            )
        logger.debug("Upserted node %s into ChromaDB.", node_id)

    def search_similar(
        self,
        query: str,
        n_results: int = 5,
        filter_project_id: Optional[str] = None
    ) -> list[dict]:
        """
        Embed a query and return the top N similar nodes.
        Optionally filter by project_id.
        Returns list of dicts with keys:
          node_id, label, description, distance, metadata
        Lower distance = more similar (cosine distance).
        """
        if self._collection.count() == 0:
            return []

        query_embedding = self._embed(query)

        where_filter = None
        if filter_project_id:
            where_filter = {"project_id": {"$eq": filter_project_id}}

        kwargs = dict(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self._collection.count()),
            include=['documents', 'metadatas', 'distances']
        )
        if where_filter:
            kwargs['where'] = where_filter

        results = self._collection.query(**kwargs)

        output = []
        if not results['ids'] or not results['ids'][0]:
            return output

        for i, node_id in enumerate(results['ids'][0]):
            output.append({
                'node_id': node_id,
                'label': results['metadatas'][0][i].get('label', ''),
                'description': results['documents'][0][i],
                'distance': results['distances'][0][i],
                'metadata': results['metadatas'][0][i]
            })
        return output

    def delete_node(self, node_id: str) -> None:
        """Remove a node from the vector store."""
        with self._write_lock:
            self._collection.delete(ids=[node_id])
        logger.debug("Deleted node %s from ChromaDB.", node_id)

    def get_node(self, node_id: str) -> Optional[dict]:
        """
        Retrieve a single node's embedding record by ID.
        Returns None if not found.
        """
        results = self._collection.get(
            ids=[node_id],
            include=['documents', 'metadatas']
        )
        if not results['ids']:
            return None
        return {
            'node_id': results['ids'][0],
            'description': results['documents'][0],
            'metadata': results['metadatas'][0]
        }

    def count(self) -> int:
        """Return total number of documents in the collection."""
        return self._collection.count()

    def get_collection_stats(self) -> dict:
        """Return stats about the vector store."""
        return {
            'collection_name': COLLECTION_NAME,
            'document_count': self._collection.count(),
            'persist_dir': str(self.persist_dir),
            'embedding_model': EMBEDDING_MODEL
        }


if __name__ == "__main__":
    import json
    print("Testing MAIHERA VectorStore...")

    store = VectorStore()
    store.initialize()
    print("Initialized. Documents in collection:",
          store.count())

    # Test upsert
    store.upsert_node(
        node_id="test-001",
        description=(
            "Fix the personality accuracy bug in Presence "
            "where the AI does not respond like Yash"
        ),
        metadata={
            "type": "issue",
            "project_id": "presence-project",
            "status": "active",
            "label": "Presence — Personality Accuracy"
        }
    )
    store.upsert_node(
        node_id="test-002",
        description=(
            "Build the MAIHERA morning briefing system "
            "with voice output and graph animation"
        ),
        metadata={
            "type": "task",
            "project_id": "maihera-project",
            "status": "active",
            "label": "MAIHERA — Morning Briefing"
        }
    )
    store.upsert_node(
        node_id="test-003",
        description=(
            "Implement Cartesia voice cloning for "
            "Presence speech-to-speech mode"
        ),
        metadata={
            "type": "feature",
            "project_id": "presence-project",
            "status": "active",
            "label": "Presence — Voice Cloning"
        }
    )
    print("Upserted 3 test nodes.")

    # Test search
    results = store.search_similar(
        "voice and speech features", n_results=3
    )
    print("\nSearch results for 'voice and speech features':")
    for r in results:
        print(f"  [{r['distance']:.3f}] {r['label']}")

    # Test project filter
    presence_results = store.search_similar(
        "AI personality simulation",
        n_results=5,
        filter_project_id="presence-project"
    )
    print("\nFiltered search (Presence only):")
    for r in presence_results:
        print(f"  [{r['distance']:.3f}] {r['label']}")

    # Test get_node
    node = store.get_node("test-001")
    print("\nGet node test-001:", node['metadata']['label']
          if node else "NOT FOUND")

    # Test delete
    store.delete_node("test-001")
    store.delete_node("test-002")
    store.delete_node("test-003")
    print("Test nodes cleaned up.")

    stats = store.get_collection_stats()
    print("\nCollection stats:", json.dumps(stats, indent=2))
    print("\nVectorStore test PASSED.")