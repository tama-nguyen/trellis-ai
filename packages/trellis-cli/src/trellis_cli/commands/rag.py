"""``trellis rag index``, ``trellis rag query`` and ``trellis rag providers``.

These commands are wired to the protocols in ``trellis_rag``, not to a particular provider: the
embedder and the vector store are looked up by name in the plugin registries, so the same two
commands exercise the built-in in-memory stack today and a product's embedding API and vector
database once it registers them (``trellis rag providers`` lists what is installed).
"""

from pathlib import Path

import click

from trellis_cli.output import CliState, announce, emit
from trellis_core.errors import ExitCode
from trellis_core.json_types import JsonObject, JsonValue
from trellis_core.plugins import PluginRegistry, get_plugin_meta
from trellis_rag.chunking import FixedSizeChunker
from trellis_rag.config import (
    ChunkingConfig,
    EmbeddingConfig,
    RetrievalConfig,
    VectorStoreConfig,
)
from trellis_rag.indexing import IndexingPipeline
from trellis_rag.registry import (
    build_document_source,
    build_embedder,
    build_vector_store,
    document_source_registry,
    embedder_registry,
    vector_store_registry,
)
from trellis_rag.retrieval import VectorRetriever

#: Without a snapshot file an index built by one command cannot be queried by the next one, so the
#: CLI defaults to a file; a service keeps its store open instead and never needs this.
DEFAULT_STORE_PATH = Path(".trellis/rag-index.json")


@click.group("rag")
def rag_group() -> None:
    """Index documents and query them (retrieval-augmented generation building blocks)."""


@rag_group.command("index")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--source", "source_provider", default="text-file", show_default=True)
@click.option("--embedder", "embedder_provider", default="hashing", show_default=True)
@click.option("--store-provider", default="memory", show_default=True)
@click.option("--dimensions", default=256, show_default=True, help="Embedding vector width.")
@click.option("--chunk-size", default=1200, show_default=True, help="Characters per chunk.")
@click.option("--chunk-overlap", default=150, show_default=True)
@click.option("--dry-run", is_flag=True, help="Chunk and embed, but write nothing to the store.")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_STORE_PATH,
    show_default=True,
    help="Snapshot file of the `memory` store; providers that keep their own state ignore it.",
)
@click.pass_obj
def index_command(
    state: CliState,
    paths: tuple[Path, ...],
    source_provider: str,
    embedder_provider: str,
    store_provider: str,
    dimensions: int,
    chunk_size: int,
    chunk_overlap: int,
    dry_run: bool,
    store_path: Path,
) -> int:
    """Index PATHS (files or directories) into the vector store."""
    embedding = EmbeddingConfig(provider=embedder_provider, dimensions=dimensions)
    embedder = build_embedder(embedding)
    store_config = VectorStoreConfig(
        provider=store_provider, options={} if dry_run else {"path": str(store_path)}
    )
    store = build_vector_store(store_config, embedder.dimensions())
    source = build_document_source(
        source_provider, {"paths": [str(path) for path in paths], "root": str(Path.cwd())}
    )
    chunker = FixedSizeChunker(
        ChunkingConfig(max_characters=chunk_size, overlap_characters=chunk_overlap)
    )
    if dry_run:
        announce("dry run: nothing is written to the store")
    try:
        report = IndexingPipeline(chunker, embedder, store, batch_size=embedding.batch_size).run(
            source
        )
        stored = store.count()
    finally:
        store.close()
    data: JsonObject = {
        "documents": report.documents_read,
        "chunks_written": report.chunks_written,
        "chunks_replaced": report.chunks_replaced,
        "chunks_in_store": stored,
        "store": None if dry_run else str(store_path),
        "dry_run": dry_run,
    }
    emit(
        state,
        data,
        f"indexed {report.documents_read} document(s), "
        f"{report.chunks_written} chunk(s); store holds {stored}",
    )
    return ExitCode.OK


@rag_group.command("query")
@click.argument("text")
@click.option("--embedder", "embedder_provider", default="hashing", show_default=True)
@click.option("--store-provider", default="memory", show_default=True)
@click.option("--dimensions", default=256, show_default=True)
@click.option("--top-k", default=5, show_default=True)
@click.option("--min-score", default=0.0, show_default=True)
@click.option("--snippet", default=160, show_default=True, help="Characters of chunk text shown.")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_STORE_PATH,
    show_default=True,
    help="Snapshot file of the `memory` store; providers that keep their own state ignore it.",
)
@click.pass_obj
def query_command(
    state: CliState,
    text: str,
    embedder_provider: str,
    store_provider: str,
    dimensions: int,
    top_k: int,
    min_score: float,
    snippet: int,
    store_path: Path,
) -> int:
    """Retrieve the chunks that match TEXT, best first."""
    embedder = build_embedder(EmbeddingConfig(provider=embedder_provider, dimensions=dimensions))
    store = build_vector_store(
        VectorStoreConfig(provider=store_provider, options={"path": str(store_path)}),
        embedder.dimensions(),
    )
    try:
        retriever = VectorRetriever(
            embedder, store, RetrievalConfig(top_k=top_k, min_score=min_score)
        )
        hits = retriever.retrieve(text)
        rows: list[JsonValue] = []
        lines: list[str] = []
        for rank, hit in enumerate(hits, start=1):
            excerpt = hit.chunk.text[:snippet]
            rows.append(
                {
                    "rank": rank,
                    "score": round(hit.score, 6),
                    "doc_id": hit.chunk.doc_id,
                    "chunk_id": hit.chunk.chunk_id,
                    "text": excerpt,
                }
            )
            lines.append(f"{rank:>2}. {hit.score:<10.4f} {hit.chunk.chunk_id}\n    {excerpt}")
        emit(state, {"query": text, "hits": rows}, "\n".join(lines) or "no matching chunks")
    finally:
        store.close()
    return ExitCode.OK


@rag_group.command("providers")
@click.pass_obj
def providers_command(state: CliState) -> int:
    """List the installed source, embedder and vector-store providers."""
    data: JsonObject = {}
    lines: list[str] = []
    # Three calls rather than a dict of registries: PluginRegistry is invariant, so a dict would
    # erase the element type and with it every check inside the helper.
    _collect("sources", document_source_registry(), data, lines)
    _collect("embedders", embedder_registry(), data, lines)
    _collect("stores", vector_store_registry(), data, lines)
    emit(state, data, "\n".join(lines))
    return ExitCode.OK


def _collect[T](kind: str, registry: PluginRegistry[T], data: JsonObject, lines: list[str]) -> None:
    """``load=True``: importing every provider is what turns a broken one into a visible
    "disabled, because ..." row instead of a name that fails later at run time."""
    rows: list[JsonValue] = []
    lines.append(kind)
    for status in registry.summary(load=True):
        meta = None if status.state != "loaded" else get_plugin_meta(registry.get(status.name))
        description = meta.description if meta else None
        rows.append(
            {
                "name": status.name,
                "state": status.state,
                "reason": status.reason,
                "description": description,
            }
        )
        lines.append(f"  {status.name:<16} {status.state:<9} {status.reason or description or ''}")
    data[kind] = rows
