"""Splitting a document into retrievable chunks: the :class:`Chunker` seam and a fixed-size one."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from trellis_rag.config import ChunkingConfig
from trellis_rag.model import Chunk, Document, chunk_id_for


@runtime_checkable
class Chunker(Protocol):
    """Turns one document into the units that are embedded, scored and shown to an LLM."""

    def split(self, document: Document) -> Sequence[Chunk]: ...


class FixedSizeChunker:
    """Windows of at most ``max_characters`` with ``overlap_characters`` carried over.

    The window ends at the last paragraph or sentence break inside it when there is one, because a
    chunk cut mid-sentence retrieves badly: the embedding of half a sentence matches neither the
    question nor the answer. Overlap keeps a fact that straddles a boundary present in both chunks.
    """

    #: Tried in order; the first break found in the tail of the window wins.
    BREAKS = ("\n\n", "\n", ". ", " ")

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self._config = config or ChunkingConfig()

    def split(self, document: Document) -> Sequence[Chunk]:
        text = document.text.strip()
        if not text:
            return ()
        size = self._config.max_characters
        overlap = self._config.overlap_characters
        chunks: list[Chunk] = []
        start = 0
        while start < len(text):
            end = self._break_at(text, start, min(start + size, len(text)))
            piece = text[start:end].strip()
            if piece:
                index = len(chunks)
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id_for(document.doc_id, index),
                        doc_id=document.doc_id,
                        index=index,
                        text=piece,
                        metadata=dict(document.metadata),
                    )
                )
            if end >= len(text):
                break
            # max(...) guarantees progress even if a break landed inside the overlap window.
            start = max(end - overlap, start + 1)
        return tuple(chunks)

    def _break_at(self, text: str, start: int, end: int) -> int:
        if end >= len(text):
            return len(text)
        # Only look in the last quarter of the window: an earlier break would waste most of it.
        floor = start + (end - start) * 3 // 4
        for marker in self.BREAKS:
            cut = text.rfind(marker, floor, end)
            if cut != -1:
                return cut + len(marker)
        return end
