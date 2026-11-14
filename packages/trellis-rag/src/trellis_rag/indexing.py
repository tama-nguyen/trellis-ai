"""The write side: source -> chunker -> embedder -> vector store, with a run report.

Batching is the whole point of this module. An embedding API is charged and rate-limited per call,
so chunks are accumulated to ``batch_size`` before being embedded, and a document's old chunks are
deleted before its new ones are written so a shortened document leaves nothing behind.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from trellis_core.instrumentation import instrumented
from trellis_core.logs import bound_log_context, get_logger
from trellis_core.report import Report
from trellis_rag.chunking import Chunker
from trellis_rag.embedding import Embedder
from trellis_rag.model import Chunk, Document, EmbeddedChunk
from trellis_rag.sources import DocumentSource
from trellis_rag.store import VectorStore

_log = get_logger(__name__)


@dataclass
class IndexReport(Report):
    documents_read: int = 0
    documents_failed: int = 0
    chunks_written: int = 0
    chunks_replaced: int = 0


class IndexingPipeline:
    """Runs one indexing pass. Not a worker: an event worker or a CLI command owns the lifecycle
    and calls :meth:`run`, exactly as the event pipeline owns delivery for its actions."""

    def __init__(
        self,
        chunker: Chunker,
        embedder: Embedder,
        store: VectorStore,
        *,
        batch_size: int = 64,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._batch_size = batch_size

    @instrumented("rag.index")
    def run(self, source: DocumentSource, report: IndexReport | None = None) -> IndexReport:
        result = report or IndexReport()
        batch: list[Chunk] = []
        for document in source.documents():
            result.increment("documents_read")
            with bound_log_context(doc_id=document.doc_id):
                result.increment("chunks_replaced", self._store.delete_document(document.doc_id))
                batch.extend(self._chunker.split(document))
                while len(batch) >= self._batch_size:
                    self._flush(batch[: self._batch_size], result)
                    del batch[: self._batch_size]
        if batch:
            self._flush(batch, result)
        _log.info(
            "indexing finished",
            documents=result.documents_read,
            chunks=result.chunks_written,
            stored=self._store.count(),
        )
        return result

    def _flush(self, chunks: Sequence[Chunk], report: IndexReport) -> None:
        vectors = self._embedder.embed([chunk.text for chunk in chunks])
        embedded = [
            EmbeddedChunk(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        report.increment("chunks_written", self._store.upsert(embedded))


def documents_of(items: Sequence[Document]) -> DocumentSource:
    """Adapts a list of documents to :class:`~trellis_rag.sources.DocumentSource` (tests, workers
    that already hold the document they just received as an event)."""
    return _ListSource(items)


class _ListSource:
    def __init__(self, items: Sequence[Document]) -> None:
        self._items = tuple(items)

    def documents(self) -> Iterator[Document]:
        return iter(self._items)
