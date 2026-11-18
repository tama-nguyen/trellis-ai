---
name: new-worker
description: >
  Add a Kafka worker to trellis-ai: the three files, the entry point, the pipeline roles the worker
  supplies, idempotency through the inbox, the two failure modes, the health endpoint, and the dry
  runs that prove it. Use when asked to add or scaffold a worker, a consumer or an event handler.
---

# Add a worker

The framework owns delivery — source, retries with backoff, DLQ, acknowledgement, offsets,
shutdown. A worker supplies only the parts. The reference is `../../AGENTS.md` "Workers"; read it
rather than guessing, and do not restate it here. `apps/notice-stats/` is the working example to
copy.

---

## Multi-agent compatibility

Nothing here is agent-specific: a shell, a text editor and `git` are enough. Claude Code users get
the read-only `uv run` commands pre-allowed by `.claude/settings.json`.

---

## 1. What a worker is made of

At minimum three files under `apps/<name>/`, mirroring `apps/notice-stats/` (which splits the
action and its store into their own modules once they grow). `<name>` is hyphenated; the package
directory is the underscored form, `src/trellis_<name_with_underscores>/`:

| File | Holds |
| --- | --- |
| `pyproject.toml` | the entry point `[project.entry-points."trellis.workers"] <name> = "trellis_<name>.worker:<Class>"` — without it the worker does not exist |
| `.../config.py` | a `ConfigModel` for the `[worker]` section, so bad config fails at startup |
| `.../worker.py` | `@plugin(...) class X(WorkerDefinition)` whose `build()` validates the config and returns `WorkerParts(...)` |

An example `<name>.example.toml` beside them documents the `[worker]` section, as
`apps/notice-stats/notice-stats.example.toml` does.

---

## 2. The four pipeline roles

`packages/trellis-events/src/trellis_events/pipeline/roles.py` defines them: `EventSource`,
`Filter`, `Transformer`, `Action`. The **source is the framework's** — Kafka or in-memory,
chosen by `TRELLIS_EVENTS_TRANSPORT`. The worker returns the other three in `WorkerParts`, plus
`event_types`, and optionally `status`, `ready` and `close`:

- **filters** decide what this worker ignores; cheap, no side effects.
- **transformers** reshape or drop an event (`None` drops it, acknowledged).
- **action** is the one place with side effects, and the only place that can fail meaningfully.

If something belongs to delivery rather than to the business of this worker, it is already
implemented — do not re-add it.

---

## 3. The inbox: make the action idempotent

Delivery is at-least-once, so the action will see the same event twice. Wrap every side effect in
`inbox.transaction(event_id, correlation_id)`; `None` back from it means *duplicate, already done*
and the action returns. A side effect outside the database uses `event_id` as the remote
idempotency key.

`consumer_name` is both the inbox key and the Kafka group id. Pick it once. Renaming it later
reprocesses the whole topic and voids every inbox entry, so it is a breaking change, not a tidy-up.

---

## 4. Failure modes

| Situation | What to do | What happens |
| --- | --- | --- |
| Retrying cannot help (bad payload, a rule that will never pass) | `raise PermanentError` | straight to `<eventType>.dlq`, then acknowledged |
| Anything else (broker blip, a dependency down) | let the exception out | retried with backoff |
| Work that finishes later | `return False` from `act()`, then `event.settle()` when it completes | the event stays unacknowledged until then |

The DLQ write happens **before** the acknowledgement; if the publish fails the event is not
acknowledged and the pipeline stops. Do not build a path around that.

---

## 5. Health

Every long-running worker gets the health server (not `--input` runs; with `--config` only when
`[health] enabled = true`): `/health/live`, `/health/ready`, `/metrics` on
`TRELLIS_HEALTH_HOST`/`TRELLIS_HEALTH_PORT`. Readiness means the poll loop is alive, the broker and
the inbox database answer, and no shutdown is in progress — so give `WorkerParts.ready` a check for
**this worker's own** dependencies. Liveness never checks dependencies.

If the worker needs its own Postgres tables, ship dev/test DDL as `*.dev.sql` package data;
deployed environments get the schema from the backend's Liquibase changelog, not from here.

---

## 6. Prove it

```bash
uv sync
uv run trellis worker list                                     # the entry point is discovered
uv run trellis worker run <name> --dry-run                     # config validates, parts wire up
uv run trellis worker run <name> --input contracts-snapshot/examples/<event>.json
uv run trellis worker health <name>                            # against a running worker
uv run ruff check . && uv run mypy && uv run pytest
```

An in-memory run with `--input` is the cheapest way to see the action execute; run it twice to see
the inbox refuse the duplicate.

Then review the result against `../review/SKILL.md` — `standards/python.md` has the delivery and
secret rules this skill assumes.
