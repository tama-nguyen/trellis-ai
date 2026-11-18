# Trellis AI review rules (Python)

Rule shape adapted from DataHub (https://github.com/datahub-project/datahub), file
`.cursor/BUGBOT.md`, commit `1415bedd`. Copyright 2015 LinkedIn Corp. and DataHub contributors,
Apache License 2.0. **Only the "if X, then flag it, with this title" format is taken; every rule
below is Trellis's own**, sourced from `AGENTS.md` at the repo root. See NOTICE.

Each rule: the trigger, what to say, the title to file it under. Prefer correctness, secrets and
delivery semantics over style — ruff format owns formatting, ruff and mypy own the mechanical rules.

Every rule below is stated in the repo-root `AGENTS.md`, which is self-contained: this repo has no
parent `AGENTS.md`.

---

## Typing

If `Any` appears — as an annotation, a cast, or implicitly through a missing annotation — then:

- Flag it: `mypy --strict` plus `disallow_any_explicit`. Untyped JSON is
  `trellis_core.json_types.JsonValue` / `JsonObject`, and foreign data is validated with
  `as_json_value`.
- Title: "No Any"
- Severity: high.

If the wrong data carrier is chosen, then:

- Flag it and name the right one: **pydantic** for anything from outside (config, envelopes,
  payloads, HTTP bodies), **`@dataclass`** for internal data and reports, **`Protocol`** for an
  interface, **`TypedDict`** only for raw JSON in tests.
- Title: "Wrong data carrier"

If pre-3.12 syntax is used where the modern form exists (`TypeVar` + `Generic` instead of
`class Foo[T]`, `TypeAlias` instead of `type Alias = ...`, `Optional[X]` instead of `X | None`,
`List`/`Dict` instead of the builtins), then:

- Flag it.
- Title: "Python 3.12 syntax"
- Severity: medium.

If an `__init__.py` gains a re-export, then:

- Flag it: `__init__.py` holds a docstring only; import the module that owns the thing.
- Title: "Re-export in __init__.py"

If a new package or module is added without `py.typed` / the `src/` layout its siblings use, then:

- Flag it.
- Title: "Package layout"

---

## Configuration, environment, secrets

If a configuration class does not extend `trellis_core.config.ConfigModel`, then:

- Flag it: `ConfigModel` gives `extra="forbid"`, keeps input out of validation errors and registers
  secrets for masking. A bare `BaseModel` loses all three.
- Title: "Config must extend ConfigModel"
- Severity: high.

If `os.environ` or `os.getenv` is read anywhere other than `trellis_core/env_vars.py`, then:

- Blocking (ruff bans it). Add a typed field with a docstring in `env_vars.py`, prefixed
  `TRELLIS_`.
- Title: "Environment read outside env_vars.py"

If a credential is typed as `str` rather than `SecretStr`, or a secret is put into `os.environ`, a
URL query string, a log message or a hand-built exception message, then:

- Blocking. Every credential is `SecretStr`; config is printed only through
  `model_dump_redacted()`.
- Title: "Secret can leak"

If a config file format other than `.toml` / `.json` is accepted, or `${VAR}` expansion is
re-implemented, or an unset variable is allowed to resolve to empty, then:

- Flag it: expansion is central, an unset variable is an error, and every expanded value is treated
  as a secret.
- Title: "Config loading rules"

---

## Logging and tracing

If `print` is used, or `logging.getLogger` appears in library code, or %-formatting is used, then:

- Flag it: `log = get_logger(__name__)`, then `log.info("event happened", key=value)`. ruff `T20`
  catches `print`.
- Title: "Logging shape"

If variable data is interpolated into the log or report *message* instead of passed as a field,
then:

- Flag it: messages are constants (`LiteralString` in `Report`); the values go in fields or
  `context`. An f-string message cannot be grouped or searched.
- Title: "Message is not a constant"

If anything is written to stdout other than command output, then:

- Flag it: logs are JSON lines on **stderr**; stdout belongs to the command's result.
- Title: "stdout is for command output"

If a log level is misused — ERROR for something no human must act on, or an expected condition
logged above INFO — then:

- Flag it: ERROR = a human must act; WARNING = unusual but handled; INFO = lifecycle; DEBUG = off
  in production.
- Title: "Log level"

If per-unit context is bound by hand where `bound_log_context(...)` exists, or a field the pipeline
already binds (`event_id`, `correlation_id`, `trace_id`, `topic`, `partition`, `offset`,
`consumer`) is re-bound, then:

- Flag it.
- Title: "Duplicate log context"

If telemetry is added, or tracing is turned on by default, then:

- Blocking for product telemetry: there is none, ever. Tracing is OpenTelemetry, off unless
  `TRELLIS_OTEL_ENABLED=true`.
- Title: "Telemetry"

---

## Workers and delivery semantics

If a worker plugin class is added without `@plugin(name=, description=, config=, status=)`, or
without the `[project.entry-points."trellis.workers"]` entry in its `pyproject.toml`, then:

- Flag it: discovery is by entry point, and `trellis worker list` and the docs read the decorator.
- Title: "Worker not registered"
- Severity: high.

If a worker's `build()` returns parts without validating its config through its own `ConfigModel`,
then:

- Flag it: a bad `[worker]` section must fail at startup, not at the first event.
- Title: "Worker config not validated"

If a side effect in an action is not wrapped in `inbox.transaction(event_id, correlation_id)`, or
the `None` it returns (duplicate) is not handled, then:

- Blocking. Delivery is at-least-once: the action must be idempotent. A side effect outside the
  database uses `event_id` as the remote idempotency key.
- Title: "Action is not idempotent"

If an event is acknowledged before the DLQ write succeeded, or a DLQ publish failure is swallowed,
then:

- Blocking. In `CONTINUE` failure mode the event is published to `<eventType>.dlq` **and only
  then** acknowledged; a failed publish means the event stays unacknowledged and the pipeline
  stops. Losing that ordering loses events silently.
- Title: "Acknowledged before the DLQ write"

If an error that a retry could fix is raised as `PermanentError`, or an error no retry can fix is
left to the retry loop, then:

- Flag it: `PermanentError` goes straight to the DLQ; everything else is retried with backoff.
- Title: "Wrong failure class"
- Severity: high.

If `act()` returns `False` for anything other than deferred work, or deferred work never calls
`event.settle()`, then:

- Flag it: `False` holds the event unacknowledged until `settle()`; forgetting it stalls the
  partition.
- Title: "Deferral never settled"

If a worker re-implements what the framework owns — the source, retries, backoff, the DLQ,
acknowledgement, offsets, shutdown — then:

- Flag it: a worker supplies only the four pipeline roles (source is the framework's; the worker
  gives filters, transformers and the action) plus `status`, `ready` and `close`.
- Title: "Worker re-implements the framework"

If `consumer_name` changes for an existing worker, then:

- Blocking: it is the inbox key and the Kafka group id. Renaming it reprocesses the whole topic and
  voids every inbox entry.
- Title: "consumer_name renamed"

If a long-running worker is added without a readiness story — `ready` covering its own
dependencies, so `/health/ready` means the poll loop is alive, the broker and the inbox answer and
no shutdown is in progress — then:

- Flag it. Liveness never checks dependencies.
- Title: "Readiness incomplete"

---

## Decorators

If a decorator is invented for something a function call states more clearly, then:

- Flag it: a decorator earns its place only by removing a cross-cutting concern from many call
  sites. The existing ones are `@plugin` and `@instrumented`.
- Title: "Unnecessary decorator"

If `@instrumented` wraps a function that is already instrumented, or a CLI command adds it by hand,
then:

- Flag it: it never wraps twice, and CLI commands get it automatically.
- Title: "Double instrumentation"

---

## Generated code and contracts

If a file under `trellis_events/generated/` or `trellis_sdk/generated/` is edited, then:

- Blocking. Change the schema in trellis-backend; models and the API client are generated there
  and, until `trellis-contracts` is published, mirrored by
  `scripts/update-contracts-snapshot.sh` (see
  [`contracts-snapshot/README.md`](../../../contracts-snapshot/README.md)).
- Title: "Generated file edited by hand"

If a file under `contracts-snapshot/` is edited, then:

- Blocking, for the same reason: it is a read-only mirror, and `SOURCE.txt` records the commit.
- Title: "Contracts mirror edited"

If an existing event payload version is changed in shape, then:

- Blocking: a breaking change is a new version, not an edit.
- Title: "Breaking event payload change"

If a worker calls the REST SDK for data the backend already publishes as an event, then:

- Flag it: workers consume events; the client is for changing state the backend owns.
- Title: "REST where an event exists"

If a generated SDK response is re-validated or re-shaped by hand, then:

- Flag it: `TrellisHttpClient.request` already applies retries, `Retry-After`, token refresh,
  correlation and trace headers, and `ProblemDetail` -> `ApiError`, and validates into the models.
- Title: "Re-implementing the SDK client"

---

## CLI

If a command does not return an `ExitCode`, writes its result with something other than
`emit(state, data, text)`, puts banners on stdout instead of `announce()`, or has side effects
without `--dry-run`, then:

- Flag the specific one: `--format json` depends on `emit`.
- Title: "CLI command conventions"

If an expected failure is raised as a bare `Exception` instead of a `TrellisError` subclass, then:

- Flag it: `main()` maps `TrellisError` to exit codes; anything else surfaces as a crash.
- Title: "Expected failure is not a TrellisError"

---

## Dependencies and tests

If a dependency is added to the workspace root instead of the package that needs it, then:

- Flag it: `uv add --package trellis-events httpx`.
- Title: "Dependency in the wrong package"

If a version constraint that is not the obvious "next major" has no comment saying why, then:

- Flag it: a CVE id or an upstream bug.
- Title: "Unexplained version pin"

If `freezegun` is used, or time is frozen any other way than
`@time_machine.travel(..., tick=False)`, then:

- Flag it: freezegun does not understand pydantic v2 datetimes and is banned in `pyproject.toml`.
- Title: "Time freezing"

If a test reads a path from the working directory instead of `tests/support.py`, assumes a timezone
other than UTC, or leaves telemetry on, then:

- Flag it: `tests/conftest.py` forces UTC and telemetry off.
- Title: "Test environment assumptions"

If an integration test does not start and remove its own container on a free localhost port, or
is not marked `integration`, then:

- Flag it: that marker is deselected by default and the container lifecycle belongs to the test.
- Title: "Integration test hygiene"

If a test exercises pydantic, click or the stdlib rather than our code, then:

- Flag it: a test must be able to catch a real regression.
- Title: "Test of framework behaviour"

---

## Confidentiality

If a real customer name, hostname, database or table name from a real system, or an internal
ticket id appears in code, tests, fixtures, comments or a commit message, then:

- Blocking. Use `example.test` domains and neutral sample data.
- Title: "Confidentiality"
