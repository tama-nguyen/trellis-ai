"""Configuration of a RAG pipeline: one :class:`~trellis_core.config.ConfigModel` tree.

Every stage is named by a **plugin name**, not by an import path, so a product swaps an embedding
API or a vector database without touching this package (see :mod:`trellis_rag.registry`). The
provider's own settings go in its ``options`` object, which that provider validates with a
``ConfigModel`` of its own; keeping them untyped here would be the only way to let an unknown
provider carry unknown keys, and ``extra="forbid"`` would reject them.
"""

from typing import Self

from pydantic import Field, model_validator

from trellis_core.config import ConfigModel
from trellis_core.json_types import JsonObject

#: Built-in plugin names. They need no service and exist so the package is runnable and testable;
#: a product registers its own and names it here.
MEMORY_STORE = "memory"
HASHING_EMBEDDER = "hashing"
TEXT_FILE_SOURCE = "text-file"


class ChunkingConfig(ConfigModel):
    """Fixed-size chunking in characters, not tokens: the character count is exact for every
    language and needs no tokenizer. A provider that charges per token re-chunks its own way."""

    max_characters: int = Field(default=1200, ge=64, le=100_000)
    overlap_characters: int = Field(default=150, ge=0)

    @model_validator(mode="after")
    def _overlap_fits(self) -> Self:
        if self.overlap_characters >= self.max_characters:
            raise ValueError("overlap_characters must be smaller than max_characters")
        return self


class EmbeddingConfig(ConfigModel):
    provider: str = HASHING_EMBEDDER
    """Plugin name in the ``trellis.rag.embedders`` group."""
    dimensions: int = Field(default=256, ge=8, le=8192)
    """Vector width. A real provider's model decides this; the value here must match it."""
    batch_size: int = Field(default=64, ge=1, le=1024)
    options: JsonObject = Field(default_factory=dict)
    """Provider-specific settings, validated by the provider."""


class VectorStoreConfig(ConfigModel):
    provider: str = MEMORY_STORE
    """Plugin name in the ``trellis.rag.stores`` group."""
    options: JsonObject = Field(default_factory=dict)


class RetrievalConfig(ConfigModel):
    top_k: int = Field(default=5, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Hits below this similarity are dropped. 0.0 keeps everything that is not opposite."""


class RagConfig(ConfigModel):
    """The ``[rag]`` section of a worker or service config file."""

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
