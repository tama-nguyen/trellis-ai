# Trellis AI — Python workers, RAG, SDK and CLI

Canonical guide for this repo, for humans and agents alike. It is self-contained: this repo has no
parent `AGENTS.md`. Overview and what each package is for: `README.md`. How the three repos talk to
each other: `docs/architecture/cross-repo.md` in a **trellis-backend** checkout.

This repo holds **no business domain**. It is the machinery a product plugs into: the worker
contract and its delivery guarantees, the RAG seams, configuration, logging and tracing, a typed
client for the backend API, and one sample worker showing the whole path.

## Sibling repos (decision T21)

| Repo | What it owns |
| --- | --- |
| `trellis-backend` | Java 21 / Spring Boot: the database, the business rules, `contracts/`, and the local infrastructure stack (decision T23) |
| `trellis-web` | Next.js frontend, and the BFF for the browser |
| `trellis-ai` | this repo |

No repo imports another's source. This repo reaches the backend over REST through `trellis-sdk`, and
receives events over Kafka; it never reads the backend's database except its own inbox and worker
tables.

## Commands

Run from the **repo root**. Always through `uv run`, so the locked tool versions apply.

```bash
uv sync                          # create/refresh .venv from uv.lock (Python 3.12 is fetched by uv)
uv run ruff format               # format (CI: uv run ruff format --check)
uv run ruff check                # lint; --fix for the safe fixes
uv run mypy                      # strict type check of packages, apps and tests
uv run pytest                    # tooling + contract tests (integration tests deselected)
uv run pytest --cov              # same + coverage.xml (Cobertura, for CI)
uv run pytest -m integration     # starts its own Postgres 17 container (needs Docker)
uv run trellis --help            # the CLI
uv run trellis worker list       # the registered workers, and why any are disabled
uv run trellis worker run notification-stats --input contracts-snapshot/examples/notification.published.v1.json
uv run trellis worker health notification-stats   # probe a running worker's /health/ready
uv run trellis events validate <file>...    # envelopes against contracts-snapshot/events
uv run trellis rag index <file>... --store /tmp/trellis-rag.json
uv run trellis rag query "..." --store /tmp/trellis-rag.json
uv run trellis rag providers     # which sources, embedders and stores are installed
scripts/update-contracts-snapshot.sh        # refresh the contract mirror (see below)
```

Add a dependency to the package that needs it (`uv add --package trellis-events httpx`), never to
the workspace root. Every version constraint that is not the obvious "next major" gets a comment
saying why (CVE id, upstream bug).

## Layout

```
pyproject.toml           workspace root (virtual): tool config, dev dependencies, members
packages/trellis-core    config, env, secrets, logging, tracing, backoff, ids, plugins, reports
packages/trellis-events  envelope, generated models, pipeline engine, inbox, transports, health,
                         worker API
packages/trellis-sdk     HTTP client for the backend + generated models and resources
packages/trellis-rag     the RAG seams: source, chunker, embedder, vector store, retriever
packages/trellis-cli     the `trellis` command
apps/<name>              one deployable worker per folder, registered by entry point
tests/<package>          tests mirror the package they cover
contracts-snapshot/      read-only mirror of the backend's contracts (temporary, see below)
scripts/                 one-off maintenance scripts; CI calls none of them
Dockerfile               the worker image
```

Workspace members are `packages/*` and `apps/*`. Each uses the `src/` layout and ships `py.typed`.
`__init__.py` files contain a docstring only: no re-exports (import the module that owns the thing).

## Code standards (all languages)

- **Comments explain why**: an external constraint, a warning, a reference. Never restate the code.
  - Bad: `# increment the retry count`
  - Good: `# The broker drops idle sockets at 60 s, so retry once before surfacing the error.`
- **No magic string or number literals** for domain values, codes, statuses, header names, routes,
  storage keys, provider names. Put them in a named constant or enum owned by the module. Exempt:
  log text and test fixtures.
- **Type everything** (see Typing below: `mypy --strict` plus no `Any`). A value object beats a
  bare `str`.
- **Generated files are never hand-edited.** Change the source (schema, contract) and regenerate.
  Generated output carries a header saying so.
- Validation and authorization live below the API layer; a hidden button is never authorization.

## Commits and confidentiality

- Conventional Commits: `type(scope): description` (`feat(rag): add pgvector store seam`).
  Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`.
- Breaking changes: `!` after the type, and say in the body what breaks, written for someone who
  does not read code.
- **Never use `--no-verify`.** A failing hook is a signal to stop and fix, not to skip. Report it
  and ask. `.claude/hooks/deny-git-no-verify.sh` enforces this for Claude Code.
- No real customer names, hostnames, database or table names from real systems, or internal ticket
  IDs in code, tests, fixtures, comments or commit messages. Use `example.test` domains and neutral
  sample data.

## Typing

- `mypy --strict` plus `disallow_any_explicit`: no `Any`, anywhere. Untyped JSON is
  `trellis_core.json_types.JsonValue`/`JsonObject`; validate foreign data with `as_json_value`.
- Pydantic for data from **outside** (config, envelopes, payloads, HTTP bodies); `@dataclass` for
  internal data and reports; `Protocol` for interfaces; `TypedDict` only for raw JSON in tests.
- Python 3.12 syntax: `class Foo[T]`, `type Alias = ...`, `X | None`, builtin generics.
- Report and log *messages* are constants (`LiteralString` in `Report`); variable data goes in
  fields/`context`, never in an f-string message.

## Configuration, environment, secrets

- Configuration classes extend `trellis_core.config.ConfigModel` (`extra="forbid"`, no input in
  validation errors, secrets registered for masking). Log or print config only via
  `model_dump_redacted()`.
- Environment variables are read **only** in `trellis_core/env_vars.py` (ruff bans `os.environ`,
  `os.getenv` and `os.putenv` elsewhere). Add a typed field there with a docstring; prefix
  `TRELLIS_`.
- Every credential is `SecretStr`. Never put a secret into `os.environ`, a URL query string, a log
  message or an exception message you build yourself.
- Config files are `.toml` or `.json`; `${VAR}` is expanded, an unset variable is an error, and every
  expanded value is treated as a secret (masked in logs).

## Logging and tracing

- `log = get_logger(__name__)`; `log.info("event happened", key=value)`. No `print` (ruff `T20`),
  no `logging.getLogger` in library code, no %-formatting.
- Logs are JSON lines on **stderr**; stdout is reserved for command output.
- Per-unit context with `bound_log_context(...)`; the pipeline already binds `event_id`,
  `correlation_id`, `trace_id`, `topic`, `partition`, `offset`, `consumer`.
- Levels: ERROR = a human must act; WARNING = unusual but handled; INFO = lifecycle; DEBUG = off in
  production.
- Tracing is OpenTelemetry, off unless `TRELLIS_OTEL_ENABLED=true`. No product telemetry, ever.

## Decorators (the Python counterpart of the Java annotations)

| Decorator | Module | Use for |
| --- | --- | --- |
| `@plugin(name=, description=, config=, status=)` | `trellis_core.plugins` | Every worker, source or sink plugin class. Docs and `trellis worker list` read it. |
| `@instrumented("span.name")` | `trellis_core.instrumentation` | A span + timing log around a function; keeps the signature (ParamSpec); never wraps twice. CLI commands get it automatically. |
| `@time_machine.travel(..., tick=False)` | tests | Freezing time. `freezegun` is banned (no pydantic v2 support). |

Do not invent a decorator for something a function call states more clearly; add one only when it
removes a cross-cutting concern from many call sites (as the AOP rules of the Java side, T8).

## Workers

The framework owns delivery: source, retries with backoff, DLQ, acknowledgement, offsets,
shutdown. A worker supplies only the parts:

1. `apps/<name>/pyproject.toml` with an entry point
   `[project.entry-points."trellis.workers"] <name> = "trellis_<name>.worker:<Class>"`, and the
   package added to the root `pyproject.toml` (dependencies and `[tool.uv.sources]`).
2. `config.py`: a `ConfigModel` for the `[worker]` section.
3. `worker.py`: `@plugin(...) class X(WorkerDefinition)` whose `build()` validates the config and
   returns `WorkerParts(event_types=..., action=..., filters=..., transformers=...)`.
4. The action is idempotent: wrap side effects in `inbox.transaction(event_id, correlation_id)`;
   `None` from it means duplicate. A side effect outside the database uses `event_id` as the remote
   idempotency key.
5. Raise `PermanentError` for "retrying cannot help" (goes straight to the DLQ); any other exception
   is retried with backoff. Return `False` from `act()` only for deferred work, and call
   `event.settle()` when it completes.
6. `uv sync`, then `uv run trellis worker run <name> --dry-run` and an in-memory run with `--input`.

`consumer_name` is the inbox key and the Kafka group id. Renaming it reprocesses the whole topic.

Step by step, against the real `notification-stats` worker: `.agent-skills/new-worker/SKILL.md`.

## RAG

`trellis-rag` is **seams, not a product**: `DocumentSource`, `Chunker`, `Embedder`, `VectorStore`,
`Retriever`, each a `Protocol`, with in-memory built-ins (`text-file`, `hashing`, `memory`) so the
CLI runs in a bare checkout with no vector database and no model API.

- Three stages are swappable at deployment time and have a registry: document source, embedder,
  vector store. A product installs a package declaring the entry point (`trellis.rag.sources`,
  `trellis.rag.embedders`, `trellis.rag.stores`), names the provider in config
  (`[rag.embedding] provider = "openai"`), and `build_embedder` calls its `from_config`.
- Chunking and retrieval have **no** registry, on purpose: choosing them is a line of code in the
  product's wiring, not a deployment-time switch.
- `PluginRegistry` imports a provider only when it is asked for, so one whose dependency is missing
  disables itself with a readable reason instead of breaking startup for everything else.
- No provider extras are declared here. An embedding API client, pgvector/Qdrant or an LLM SDK is a
  product decision; advertising empty extras would promise support that does not exist.

## Contracts: this repo generates nothing (decision T22)

The backend owns `contracts/`. Its CI generates the pydantic event models and the OpenAPI client and
publishes them as the PyPI package **`trellis-contracts`**, which this repo will pin. **There is no
code generator in this repo** — do not look for one, and do not add one.

Until that package exists:

- `packages/trellis-events/src/trellis_events/generated/` and
  `packages/trellis-sdk/src/trellis_sdk/generated/` stay **committed**. Never edit them; ruff skips
  both folders, mypy checks them.
- `contracts-snapshot/` is a read-only mirror of the backend's `events/`, `examples/` and
  `testdata/`. Never edit a file there. Change the schema in trellis-backend, then
  `scripts/update-contracts-snapshot.sh` (optionally `--from /path/to/trellis-backend/contracts`);
  `SOURCE.txt` records the backend commit the copy came from. No pipeline calls that script:
  refreshing the mirror is a deliberate, reviewed change.
- Code finds the schemas by `TRELLIS_CONTRACTS_DIR`, else by searching upwards for
  `contracts-snapshot/` or `contracts/`, so it resolves from the repo root with no setup. The
  Dockerfile copies the mirror to `/app/contracts`.

`contracts-snapshot/README.md` lists exactly what changes on the day the package is published.
A breaking contract change is a new version, not an edit.

### Envelope and payloads

`trellis_events.envelope.Envelope` subclasses the generated envelope to add behaviour; do the same
if a payload needs methods. Payloads are registered from a generated index, so none can be
forgotten.

### The backend client

```python
with TrellisClient.from_env() as client:          # TRELLIS_API_URL + TRELLIS_API_TOKEN
    page = client.notification.list_notifications(first=50, audience="ALL")
    view = client.notification.publish_notification(code, idempotency_key=str(uuid4()))
```

Every generated method calls `TrellisHttpClient.request`, so retries, `Retry-After`, token refresh,
correlation/trace headers and `ProblemDetail` -> `ApiError` apply; path parameters are URL-quoted;
responses are validated into the models (unknown fields ignored, so additive API changes do not
break workers). Resources are properties named after the OpenAPI tag (`client.notification`, `client.ops`,
`client.app_config`).

Workers consume **events**, not REST, for anything the backend publishes; use the client only to
change state the backend owns.

## Running a worker in a container

Without `--config`, `trellis worker run <name>` reads the environment:

| Variable | Meaning |
| --- | --- |
| `TRELLIS_EVENTS_TRANSPORT` | `kafka` or `inmemory` (default). In-memory without `--input` idles until SIGTERM. |
| `TRELLIS_KAFKA_BOOTSTRAP_SERVERS` | Required for `kafka`. |
| `TRELLIS_DATABASE_URL` | Worker database (inbox + worker tables). Unset = in-memory stores. Masked in logs. |
| `TRELLIS_CONTRACTS_DIR` | Where the event schemas are; the image sets `/app/contracts`. |
| `TRELLIS_HEALTH_HOST` / `TRELLIS_HEALTH_PORT` | `/health/live`, `/health/ready`, `/metrics` (default `127.0.0.1:9464`). |

The health server runs for every long-running worker (not for `--input` runs, and with `--config`
only when `[health] enabled = true`). `trellis worker health <name>` exits 0 only when
`/health/ready` is 200: the poll loop is alive (heartbeat younger than `max.poll.interval.ms`), the
broker and the inbox database answer, and no shutdown is in progress. Liveness never checks
dependencies. Dev/test DDL for the Postgres tables ships as `*.dev.sql` package data; deployed
environments get their schema from the backend's Liquibase changelog.

The local infrastructure stack (Postgres, Kafka, Keycloak) belongs to trellis-backend (decision
T23): start it there, then point these variables at it.

## Adding a CLI command

One module per command group in `trellis_cli/commands/` (`config`, `events`, `rag`, `worker`,
`version`), attached in `trellis_cli/main.py`. A command returns an `ExitCode`, writes its result
with `emit(state, data, text)` (so `--format json` works), writes banners with `announce()`
(stderr), and offers `--dry-run` if it has side effects. Raise `TrellisError` subclasses for
expected failures: `main()` maps them to exit codes.

## Agent tooling

Portable skills live in `.agent-skills/` — one folder per skill, readable by any agent
(`.agent-skills/README.md` explains the shape and how Cursor or Codex consume them).
`.agent-skills/review/` is the code-review skill for this repo (rules in
`.agent-skills/review/standards/python.md`) and `.agent-skills/new-worker/` walks adding a worker;
both link back here rather than repeating these rules. `.claude/` holds only Claude Code-specific
things: the read-only command allowlist in `settings.json` and the `--no-verify` hook.

## Testing (decision T5)

- Tests exist for **tooling and contracts only**: envelope/payload schema conformance, shared test
  vectors with Java (`contracts-snapshot/testdata/*.json`), plugin loading, config redaction, CLI
  exit codes. Do not add feature tests until the owner asks.
- `tests/integration/` (marker `integration`, deselected by default) verifies infrastructure on real
  containers it starts and removes itself (free localhost port, `docker run`): inbox and counter
  store on Postgres 17, concurrent duplicates, restart, the health endpoint.
- Tests run in UTC (forced in `tests/conftest.py`) with telemetry off; freeze time with
  `time-machine`. Paths come from `tests/support.py`, never from the working directory.
- A test must be able to catch a real regression; no tests of pydantic, click or the stdlib.
