"""Where vectors live: the :class:`VectorStore` seam and an in-memory implementation.

The real store is pgvector, Qdrant, OpenSearch or whatever the product already operates; each is a
plugin in the ``trellis.rag.stores`` group. :class:`InMemoryVectorStore` keeps this package
runnable and testable with no service at all, and can persist itself to a JSON file so that
``trellis rag index`` and ``trellis rag query`` work as two separate commands.
"""

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from pydantic import Field

from trellis_core.config import ConfigModel
from trellis_core.errors import InputError
from trellis_core.json_types import JsonObject, JsonValue, as_json_object
from trellis_core.plugins import SupportStatus, plugin
from trellis_rag.config import MEMORY_STORE, VectorStoreConfig
from trellis_rag.model import Chunk, EmbeddedChunk, ScoredChunk, Vector

#: Bumped when the on-disk shape changes; an older file is rejected instead of half-read.
SNAPSHOT_VERSION: Final = 1


@runtime_checkable
class VectorStore(Protocol):
    """Upsert by ``chunk_id``, delete by ``doc_id``, search by vector.

    Delete-by-document is part of the contract because re-indexing a changed document must remove
    the chunks it no longer has; a store that can only upsert leaves stale text to be retrieved.
    """

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> int: ...

    def delete_document(self, doc_id: str) -> int: ...

    def search(self, vector: Vector, top_k: int, min_score: float = 0.0) -> list[ScoredChunk]: ...

    def count(self) -> int: ...

    def close(self) -> None: ...


def cosine(left: Vector, right: Vector) -> float:
    """Cosine similarity. Both vectors are usually normalised already, so this is a dot product,
    but a provider that returns unnormalised vectors must still score correctly."""
    if len(left) != len(right):
        raise InputError(f"vector width mismatch: {len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 0.0 if norm == 0.0 else dot / norm


class MemoryStoreOptions(ConfigModel):
    """``[rag.store] options`` of the ``memory`` provider. Every provider validates its own
    options like this, so a typo in a config file fails at startup instead of being ignored."""

    path: Path | None = Field(default=None)
    """JSON snapshot file. Loaded on open, written on close; ``None`` keeps the index in memory."""


@plugin(
    name=MEMORY_STORE,
    description="In-process vector store with exact cosine search; optional JSON snapshot file.",
    status=SupportStatus.TESTING,
    capabilities=frozenset({"offline", "exact-search", "snapshot"}),
)
class InMemoryVectorStore:
    """Exact search over a dict. Linear in the number of chunks: fine for thousands, not for
    millions - at that size the product plugs in a real index, which is the point of the seam."""

    def __init__(self, dimensions: int, snapshot_path: Path | None = None) -> None:
        self._dimensions = dimensions
        self._snapshot_path = snapshot_path
        self._chunks: dict[str, EmbeddedChunk] = {}

    @classmethod
    def from_config(cls, config: VectorStoreConfig, dimensions: int) -> "InMemoryVectorStore":
        """The construction contract every store provider implements (see trellis_rag.registry)."""
        options = MemoryStoreOptions.model_validate(config.options)
        return cls.open(options.path, dimensions)

    def dimensions(self) -> int:
        return self._dimensions

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> int:
        for embedded in chunks:
            if len(embedded.vector) != self._dimensions:
                raise InputError(
                    f"chunk {embedded.chunk.chunk_id}: vector has {len(embedded.vector)} "
                    f"dimensions, store has {self._dimensions}"
                )
            self._chunks[embedded.chunk.chunk_id] = embedded
        return len(chunks)

    def delete_document(self, doc_id: str) -> int:
        stale = [key for key, item in self._chunks.items() if item.chunk.doc_id == doc_id]
        for key in stale:
            del self._chunks[key]
        return len(stale)

    def search(self, vector: Vector, top_k: int, min_score: float = 0.0) -> list[ScoredChunk]:
        """Ties are broken by ``chunk_id`` so the order is stable between runs. A chunk with a
        similarity of exactly zero shares nothing with the query and is never a hit, whatever
        ``min_score`` says."""
        hits = (
            ScoredChunk(item.chunk, cosine(vector, item.vector)) for item in self._chunks.values()
        )
        kept = [hit for hit in hits if hit.score > 0.0 and hit.score >= min_score]
        kept.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return kept[:top_k]

    def count(self) -> int:
        return len(self._chunks)

    def close(self) -> None:
        """Writes the snapshot when one was configured. Callers close every store the same way,
        so a command does not need to know whether its store persists itself."""
        if self._snapshot_path is not None:
            self.save(self._snapshot_path)

    # -- snapshot -----------------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Writes the whole store as one JSON object. Not a database: no concurrent writers, no
        partial update - the file is replaced through a temporary file in the same directory."""
        snapshot: JsonObject = {
            "version": SNAPSHOT_VERSION,
            "dimensions": self._dimensions,
            "chunks": [_chunk_as_json(item) for item in self._chunks.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "InMemoryVectorStore":
        raw = as_json_object(json.loads(path.read_text(encoding="utf-8")))
        if raw.get("version") != SNAPSHOT_VERSION:
            raise InputError(
                f"{path}: snapshot version {raw.get('version')!r}, expected {SNAPSHOT_VERSION}"
            )
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, int):
            raise InputError(f"{path}: snapshot has no integer 'dimensions'")
        store = cls(dimensions)
        chunks = raw.get("chunks")
        if not isinstance(chunks, list):
            raise InputError(f"{path}: snapshot has no 'chunks' array")
        store.upsert([_chunk_from_json(item) for item in chunks])
        return store

    @classmethod
    def open(cls, path: Path | None, dimensions: int) -> "InMemoryVectorStore":
        """The store behind ``--store``: load it when the file exists, otherwise start empty.
        Either way the path is remembered, so :meth:`close` writes the snapshot back."""
        if path is None or not path.exists():
            return cls(dimensions, path)
        store = cls.load(path)
        store._snapshot_path = path
        if store.dimensions() != dimensions:
            raise InputError(
                f"{path} was written with {store.dimensions()} dimensions, this embedder produces "
                f"{dimensions}; delete the file or use the embedder it was built with"
            )
        return store


def _chunk_as_json(item: EmbeddedChunk) -> JsonValue:
    return {
        "chunk_id": item.chunk.chunk_id,
        "doc_id": item.chunk.doc_id,
        "index": item.chunk.index,
        "text": item.chunk.text,
        "metadata": item.chunk.metadata,
        "vector": list(item.vector),
    }


def _chunk_from_json(raw: JsonValue) -> EmbeddedChunk:
    item = as_json_object(raw)
    chunk = Chunk(
        chunk_id=_string(item, "chunk_id"),
        doc_id=_string(item, "doc_id"),
        index=_integer(item, "index"),
        text=_string(item, "text"),
        metadata=as_json_object(item.get("metadata") or {}),
    )
    return EmbeddedChunk(chunk, _vector(item.get("vector")))


def _string(item: JsonObject, key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise InputError(f"snapshot chunk: {key!r} must be a string")
    return value


def _integer(item: JsonObject, key: str) -> int:
    value = item.get(key)
    if not isinstance(value, int):
        raise InputError(f"snapshot chunk: {key!r} must be an integer")
    return value


def _vector(value: JsonValue) -> Vector:
    if not isinstance(value, list):
        raise InputError("snapshot chunk: 'vector' must be an array")
    return [_coordinate(item) for item in value]


def _coordinate(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InputError("snapshot chunk: every vector element must be a number")
    return float(value)
