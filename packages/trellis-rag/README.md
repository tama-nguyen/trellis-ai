# trellis-rag

The seams of a retrieval-augmented generation pipeline, and nothing else. This package holds **no
product knowledge**: no prompts, no domain documents, no provider accounts.

## What it is

Five protocols, in the order data flows through them:

| Protocol | Module | Responsibility |
| --- | --- | --- |
| `DocumentSource` | `sources.py` | yields `Document`s to index (lazily) |
| `Chunker` | `chunking.py` | splits a document into retrievable `Chunk`s |
| `Embedder` | `embedding.py` | turns text into vectors |
| `VectorStore` | `store.py` | upserts chunk vectors, deletes by document, searches by vector |
| `Retriever` | `retrieval.py` | answers "which chunks match this question" |

Plus the parts that make them usable: `config.py` (a `ConfigModel` tree), `indexing.py` (the
batching write path and its run report), and `registry.py` (entry point groups so providers are
installed, not imported).

Implementations that ship with it, so the package runs and is testable with no services at all:

- `TextFileSource` - `.txt`/`.md`/`.rst` from the filesystem.
- `FixedSizeChunker` - character windows that end on a paragraph or sentence break, with overlap.
- `HashingEmbedder` - deterministic hashed bag-of-words. **Not a semantic model**: it matches
  shared words, so "car" and "automobile" score zero. Development, tests and CLI demos only.
- `InMemoryVectorStore` - exact cosine search over a dict, with an optional JSON snapshot file so
  `trellis rag index` and `trellis rag query` can be two separate commands.

## What it is not

- **No real providers.** An embedding API, pgvector, Qdrant, OpenSearch or an LLM SDK is a product
  decision with a cost, a key and a model version attached. The package declares no optional extras
  for them on purpose: a product adds the dependency and registers a plugin (see below).
- **No generation stage.** Prompt assembly, context window packing and the LLM call are not
  modelled yet. Retrieval ends at a ranked list of chunks; everything after that depends on the
  product's prompts and its model, and a seam invented before the first real use would be wrong.
- **No ingestion scheduling.** Reacting to a `*.published` event and re-indexing is a worker
  (`apps/<name>`), which uses this package; the package itself never consumes events.

## Plugging in a real provider

```toml
# my_product/pyproject.toml
[project.entry-points."trellis.rag.embedders"]
openai = "my_product.rag.openai_embedder:OpenAiEmbedder"

[project.entry-points."trellis.rag.stores"]
pgvector = "my_product.rag.pgvector_store:PgVectorStore"
```

The class implements the protocol **and** a `from_config` classmethod (`registry.py` states the
contract); its own settings come from `options` in the config file, validated by a `ConfigModel`
the provider owns, so a typo fails at startup. Then:

```toml
[rag.embedding]
provider = "openai"
dimensions = 1536
options = { model = "text-embedding-3-small" }

[rag.store]
provider = "pgvector"
options = { dsn = "${TRELLIS_DATABASE_URL}", table = "doc_chunk" }
```

Credentials follow the repo rules: `SecretStr` fields, read through `trellis_core.env_vars`, never
`os.environ`, never in a log line.

## Trying it

```bash
uv run trellis rag providers
uv run trellis rag index docs/ --store .trellis/rag-index.json
uv run trellis rag query "how is delivery guaranteed?" --store .trellis/rag-index.json --top-k 3
```
