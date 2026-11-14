"""Turning text into vectors: the :class:`Embedder` seam and a dependency-free stand-in.

A real embedder is a hosted model (an embedding API, a local sentence-transformer) and is a
**product** decision: it costs money, needs a key, pins a model version and fixes the vector width.
This package therefore ships only the seam plus :class:`HashingEmbedder`, which is not a semantic
model and must never be used to answer a user's question.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Final, Protocol, runtime_checkable

from trellis_core.config import ConfigModel
from trellis_core.plugins import SupportStatus, plugin
from trellis_rag.config import HASHING_EMBEDDER, EmbeddingConfig
from trellis_rag.model import Vector

#: Words, numbers and CJK characters; a CJK character is its own token because the script has no
#: spaces and a whitespace split would make one token out of a whole sentence.
_TOKEN = re.compile("[0-9a-z]+|[\u3400-\u9fff\uac00-\ud7af]")


@runtime_checkable
class Embedder(Protocol):
    """Embeds a batch of texts. The same text must always give the same vector: a store holds
    vectors produced earlier, and a query vector from a different model matches nothing."""

    def dimensions(self) -> int:
        """Vector width. A method, not a property: ``runtime_checkable`` protocols only support
        ``issubclass`` when every member is a method, and the plugin registry checks providers
        structurally."""
        ...

    def embed(self, texts: Sequence[str]) -> list[Vector]: ...


class HashingEmbedderOptions(ConfigModel):
    """The ``hashing`` provider takes no options; ``extra="forbid"`` turns a stray key in a config
    file into a startup error rather than a setting that silently does nothing."""


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@plugin(
    name=HASHING_EMBEDDER,
    description="Deterministic hashed bag-of-words. Development and tests only: no semantics.",
    status=SupportStatus.TESTING,
    capabilities=frozenset({"offline", "deterministic"}),
)
class HashingEmbedder:
    """The hashing trick: each token is hashed into one of ``dimensions`` buckets, weighted by
    ``1 + log(count)`` and L2-normalised, so the dot product of two vectors is their cosine.

    It matches shared *words*, not meaning: "car" and "automobile" score zero against each other.
    It is here so the pipeline, the store and the CLI can be exercised end to end without a key,
    a network call or a GPU - and so tests stay deterministic.

    ``blake2b`` rather than ``hash()``: Python salts string hashing per process, which would put
    the same token in a different bucket after every restart and silently invalidate a store.
    """

    _DIGEST_BYTES: Final = 8

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be >= 8")
        self._dimensions = dimensions

    @classmethod
    def from_config(cls, config: EmbeddingConfig) -> "HashingEmbedder":
        """The construction contract every embedder provider implements (trellis_rag.registry)."""
        HashingEmbedderOptions.model_validate(config.options)
        return cls(config.dimensions)

    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> Vector:
        counts: dict[int, int] = {}
        for token in tokenize(text):
            bucket = self._bucket(token)
            counts[bucket] = counts.get(bucket, 0) + 1
        vector = [0.0] * self._dimensions
        for bucket, count in counts.items():
            vector[bucket] = 1.0 + math.log(count)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=self._DIGEST_BYTES).digest()
        return int.from_bytes(digest, "big") % self._dimensions
