"""Answering "which chunks are relevant to this question": the :class:`Retriever` seam.

Retrieval is the stage a product is most likely to replace entirely - hybrid keyword + vector
search, a reranker, metadata filters, per-tenant partitions - so it is a protocol of its own rather
than a method on the store. :class:`VectorRetriever` is the plain vector case: embed the query with
the same embedder the chunks were embedded with, then ask the store.

Generation (handing the retrieved chunks to an LLM) is deliberately **not** modelled here: see the
package README.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from trellis_core.instrumentation import instrumented
from trellis_rag.config import RetrievalConfig
from trellis_rag.embedding import Embedder
from trellis_rag.model import ScoredChunk
from trellis_rag.store import VectorStore


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int | None = None) -> Sequence[ScoredChunk]: ...


class VectorRetriever:
    """Embed the query, search the store, drop hits below ``min_score``."""

    def __init__(
        self, embedder: Embedder, store: VectorStore, config: RetrievalConfig | None = None
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._config = config or RetrievalConfig()

    @instrumented("rag.retrieve")
    def retrieve(self, query: str, top_k: int | None = None) -> Sequence[ScoredChunk]:
        if not query.strip():
            return ()
        vector = self._embedder.embed([query])[0]
        return self._store.search(
            vector, top_k or self._config.top_k, min_score=self._config.min_score
        )
