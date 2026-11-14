"""The data that moves through a RAG pipeline: documents in, chunks stored, scored chunks out.

These are ``@dataclass`` and not pydantic models: they are internal values passed between the
stages of one process, never parsed from the outside (AGENTS.md "Typing"). What *is* parsed from
the outside - a document's metadata - is :data:`~trellis_core.json_types.JsonObject`, so a store
backend can write it to JSONB or to a payload field without a conversion of its own.
"""

from dataclasses import dataclass, field

from trellis_core.json_types import JsonObject

#: A dense vector. Plain ``list[float]`` so the package needs no numerical dependency; a provider
#: that works with numpy converts at its own boundary.
type Vector = list[float]


@dataclass(frozen=True)
class Document:
    """One retrievable unit before chunking: a page, a file, a record.

    ``doc_id`` is the caller's stable identifier. Re-indexing the same ``doc_id`` replaces its
    chunks, so an identifier that changes on every crawl silently duplicates the corpus.
    """

    doc_id: str
    text: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A slice of a document, the unit that is embedded and retrieved.

    ``chunk_id`` is ``"<doc_id>#<index>"`` so a store can be keyed by it and a re-index of one
    document can delete exactly its own rows.
    """

    chunk_id: str
    doc_id: str
    index: int
    text: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: Chunk
    vector: Vector


@dataclass(frozen=True)
class ScoredChunk:
    """A retrieval hit. ``score`` is "higher is more similar", whatever metric the store uses."""

    chunk: Chunk
    score: float


def chunk_id_for(doc_id: str, index: int) -> str:
    return f"{doc_id}#{index}"
