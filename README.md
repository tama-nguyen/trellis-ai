# Trellis AI

The Python side of Trellis: **retrieval-augmented generation (RAG) and everything that runs outside
an HTTP request**. Kafka workers that build read models and do asynchronous work, a typed client for
the backend API, and the `trellis` command line they all share.

It holds **no business domain**. What is here is the machinery a product plugs into: the worker
contract and its delivery guarantees, the RAG seams, configuration, logging and tracing, and one
sample worker that shows the whole path.

Read [AGENTS.md](AGENTS.md) before changing anything: it is the canonical guide for this repo, for
humans and for agents alike.

## Architecture

The Python services in these diagrams are this repo. Figure 3 shows where they sit among the other two; Figures 7 and 17 are the retrieval path.

### Figure 3: Trellis LMS system context

Who uses the system, the modular monolith in the middle, the stores it owns and the event backbone to the Python consumers.

![Figure 3: Trellis LMS system context](docs/figures/figure-03-system-context.png)

### Figure 7: Authorized RAG architecture

Access checks, permission-scoped retrieval, generation and cited answers.

![Figure 7: Authorized RAG architecture](docs/figures/figure-07-authorized-rag.png)

### Figure 17: How authorized RAG works at scale

Authorize before retrieval, and validate cited sources before returning an answer.

![Figure 17: How authorized RAG works at scale](docs/figures/figure-17-authorized-rag-at-scale.png)

## Sibling repos

Trellis is three repos (decision T21); this one holds only the Python side.

| Repo | What |
| --- | --- |
| `trellis-backend` | Java 21 / Spring Boot. Owns the database, the business rules, and `contracts/`, `docker/`, `scripts/dev/` |
| `trellis-web` | Next.js frontend, also the BFF |
| `trellis-ai` | This repo |

The event and API contracts are not copied by hand. The backend owns `contracts/`; its pipeline
generates the pydantic models and the API client and publishes them as the PyPI package
`trellis-contracts`, which this repo installs at a pinned version (decision T22). Until that first
publish, the generated copy lives in `contracts-snapshot/`; see AGENTS.md.

## What is in here

| Package | What it does |
| --- | --- |
| `packages/trellis-core` | config (`ConfigModel`), the one module that reads the environment, secret masking, structlog JSON logging, OpenTelemetry, `Backoff`, UUIDv7 and stable ids, the plugin registry, structured reports |
| `packages/trellis-events` | the worker framework: event envelope, the `EventSource → Filter → Transformer → Action` pipeline, retry and dead letters, the inbox that makes a handler idempotent, an executor that keeps per-key order, Kafka and in-memory transports |
| `packages/trellis-sdk` | typed HTTP client for the backend: connection reuse, retries that honour `429`/`Retry-After`, token refresh before expiry, backend `ProblemDetail` errors mapped to Python exceptions |
| `packages/trellis-rag` | the RAG seams: `DocumentSource`, `Chunker`, `Embedder`, `VectorStore`, `Retriever`, with in-memory implementations so it runs and is testable with no external service |
| `packages/trellis-cli` | the `trellis` command line |
| `apps/notification-stats` | the sample worker: consumes `notification.published`, counts it exactly once |

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/) (`mise install` reads
[mise.toml](mise.toml); uv fetches the interpreter itself).

```bash
uv sync
uv run trellis --help
```

### RAG, with nothing else running

Everything defaults to in-memory providers, so this works on a laptop with no vector database and no
model API:

```bash
uv run trellis rag index AGENTS.md README.md --store /tmp/trellis-rag.json
uv run trellis rag query "how are duplicate events handled?" --store /tmp/trellis-rag.json
uv run trellis rag providers        # which sources, embedders and stores are installed
```

Real providers — an embedding API, pgvector or Qdrant, an LLM — are plugged in per product by
registering them in the plugin registry. The in-memory embedder is a deterministic hashing stand-in:
good enough to exercise the pipeline, not a semantic model.

### A worker, with nothing else running

```bash
TRELLIS_EVENTS_TRANSPORT=inmemory uv run trellis worker run notification-stats \
  --input contracts-snapshot/examples/notification.published.v1.json
```

Feed the same file twice and the counter still moves once: the inbox drops the duplicate, which is
what makes at-least-once delivery safe.

### A worker against the real stack

Start the infrastructure from the backend repo (it owns the stack, decision T23):

```bash
cd ../trellis-backend && build-logic/scripts/dev/trellis-dev.sh up --profile full
```

```bash
export TRELLIS_EVENTS_TRANSPORT=kafka
export TRELLIS_KAFKA_BOOTSTRAP_SERVERS=localhost:19092
export TRELLIS_DATABASE_URL=postgresql://trellis:trellis@localhost:15432/trellis
uv run trellis worker run notification-stats
```

The worker serves `/health/live`, `/health/ready` and `/metrics` (Prometheus) on
`TRELLIS_HEALTH_PORT`; `trellis worker health notification-stats` exits 0 only when it is ready, which is
what the container healthcheck calls.

Full walkthrough of all three repos: `../trellis-backend/docs/guide/running.md`.

## Delivery guarantees

The worker framework is **at-least-once**, and that is a deliberate choice: it is the only mode in
which no event is lost. Two consequences every handler must live with.

- **Duplicates happen.** Make the handler idempotent; the inbox (`inbox_event`, keyed by consumer
  name and event id) does this for you when you use it.
- **Failure mode decides what happens next.** `CONTINUE` writes the event to the dead-letter topic
  and only then acknowledges it; `THROW` acknowledges nothing and stops the worker, so the event is
  redelivered after a restart and later events for the same key cannot overtake it.

Retries use exponential backoff with full jitter, with the same parameters as the Java side — both
read the vectors in `contracts/testdata/backoff.json`, so the two cannot drift apart.

## Quality gate

Run this before opening a pull request; [GitHub CI](.github/workflows/ci.yml) runs the same.
See [CI setup](docs/ci.md) for the manual `run_tests` switch and required checks.

```bash
uv lock --check
uv run ruff check && uv run ruff format --check
uv run mypy
uv run pytest
```

```bash
uv run pytest -m integration     # needs Docker; starts and removes its own containers
```

Tests exist only for the framework and tooling, not for features (decision T5): contract
conformance, the shared vectors, the plugin registry, config redaction, CLI exit codes, and the
Postgres inbox under concurrency.

## Conventions worth knowing before the first change

- Only `trellis_core.env_vars` reads the environment. Everything else takes configuration as a
  `ConfigModel`, so a setting is typed, documented and validated in one place.
- Secrets are `SecretStr` and are masked in logs by a filter that fails closed. Never pass a
  credential to a third-party SDK through `os.environ`.
- Full type annotations, no `Any` — mypy runs strict and the lint bans it.
- Generated files are never hand-edited.

The rest is in [AGENTS.md](AGENTS.md).
