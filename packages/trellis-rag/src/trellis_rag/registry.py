"""The extension point: entry point groups and the construction contract for the three
replaceable stages (document source, embedder, vector store).

A product adds a provider by installing a package that declares the entry point - nothing here
changes, and nothing registers itself as an import side effect::

    # my_product/pyproject.toml
    [project.entry-points."trellis.rag.embedders"]
    openai = "my_product.rag.openai_embedder:OpenAiEmbedder"

    [project.entry-points."trellis.rag.stores"]
    pgvector = "my_product.rag.pgvector_store:PgVectorStore"

The provider is then named in configuration (``[rag.embedding] provider = "openai"``) and built by
:func:`build_embedder`, which calls the class's ``from_config``. That method is what the
``*Provider`` protocols below require: a class that only implements
:class:`~trellis_rag.embedding.Embedder` can still be wired up directly in code, but a provider
that is *named in a config file* must also say how it is built from that file.

:class:`~trellis_core.plugins.PluginRegistry` imports a plugin only when it is asked for, so a
provider whose dependency is not installed disables itself with a readable reason instead of
breaking every other provider at startup. The built-ins (``hashing``, ``memory``, ``text-file``)
are registered lazily below, so they work in a bare checkout with no entry points at all.

Chunking and retrieval have no registry: choosing a chunker or a retriever is a line of code in the
product's wiring, not a deployment-time switch, and both are plain protocols.
"""

from typing import Final, Protocol, runtime_checkable

from trellis_core.json_types import JsonObject
from trellis_core.plugins import PluginRegistry
from trellis_rag.config import (
    HASHING_EMBEDDER,
    MEMORY_STORE,
    TEXT_FILE_SOURCE,
    EmbeddingConfig,
    VectorStoreConfig,
)
from trellis_rag.embedding import Embedder
from trellis_rag.sources import DocumentSource
from trellis_rag.store import VectorStore

EMBEDDER_ENTRY_POINT_GROUP: Final = "trellis.rag.embedders"
STORE_ENTRY_POINT_GROUP: Final = "trellis.rag.stores"
SOURCE_ENTRY_POINT_GROUP: Final = "trellis.rag.sources"

_BUILTIN_EMBEDDERS: Final = {HASHING_EMBEDDER: "trellis_rag.embedding:HashingEmbedder"}
_BUILTIN_STORES: Final = {MEMORY_STORE: "trellis_rag.store:InMemoryVectorStore"}
_BUILTIN_SOURCES: Final = {TEXT_FILE_SOURCE: "trellis_rag.sources:TextFileSource"}

_INSTALL_HINT: Final = "install the package that provides the {extra} provider"


@runtime_checkable
class EmbedderProvider(Protocol):
    @classmethod
    def from_config(cls, config: EmbeddingConfig) -> Embedder: ...


@runtime_checkable
class VectorStoreProvider(Protocol):
    @classmethod
    def from_config(cls, config: VectorStoreConfig, dimensions: int) -> VectorStore: ...


@runtime_checkable
class DocumentSourceProvider(Protocol):
    @classmethod
    def from_config(cls, options: JsonObject) -> DocumentSource: ...


def embedder_registry() -> PluginRegistry[EmbedderProvider]:
    return _registry(EmbedderProvider, EMBEDDER_ENTRY_POINT_GROUP, _BUILTIN_EMBEDDERS)


def vector_store_registry() -> PluginRegistry[VectorStoreProvider]:
    return _registry(VectorStoreProvider, STORE_ENTRY_POINT_GROUP, _BUILTIN_STORES)


def document_source_registry() -> PluginRegistry[DocumentSourceProvider]:
    return _registry(DocumentSourceProvider, SOURCE_ENTRY_POINT_GROUP, _BUILTIN_SOURCES)


def build_embedder(config: EmbeddingConfig) -> Embedder:
    return embedder_registry().get(config.provider).from_config(config)


def build_vector_store(config: VectorStoreConfig, dimensions: int) -> VectorStore:
    return vector_store_registry().get(config.provider).from_config(config, dimensions)


def build_document_source(provider: str, options: JsonObject) -> DocumentSource:
    return document_source_registry().get(provider).from_config(options)


def _registry[T](base: type, group: str, builtins: dict[str, str]) -> PluginRegistry[T]:
    registry = PluginRegistry[T](base, group, install_hint=_INSTALL_HINT)
    for name, target in builtins.items():
        registry.register_lazy(name, target)
    return registry
