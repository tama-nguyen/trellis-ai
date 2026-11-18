---
name: review
description: >
  Review a change in trellis-ai against this repo's own rules: full typing with no Any, ConfigModel
  for configuration, secrets only as SecretStr and never through os.environ, structured logging,
  idempotent worker actions, acknowledgement only after the DLQ write, generated models left alone.
  Use when reviewing a branch, an MR, or staged work before a commit.
---

# Trellis AI review

Review the Python change in front of you against `standards/python.md`. The rules there are this
repo's rules, taken from `../../AGENTS.md` and the module docstrings it points at; do not invent
new ones, and do not import conventions from other projects.

---

## Multi-agent compatibility

Everything here works in any agent (Claude Code, Cursor, Codex, Copilot, Gemini CLI): the skill is
Markdown plus `git` and `uv run` commands. There is no agent-specific step.

Claude Code only, and safely ignorable: `.claude/settings.json` pre-allows the read-only commands
below, and `.claude/hooks/deny-git-no-verify.sh` blocks `git ... --no-verify`.

---

## 1. Scope the review

```bash
git diff --stat <base>...HEAD      # whole branch
git diff --stat                    # working tree
git diff --stat --cached           # staged
```

In scope: `packages/*/src/`, `apps/*/`, `tests/`, `scripts/`, `pyproject.toml`, `uv.lock`.

Out of scope: `packages/trellis-events/src/trellis_events/generated/` and
`packages/trellis-sdk/src/trellis_sdk/generated/` — generated, skipped by ruff, regenerated from
the contracts. A hand edit to either **is** a finding ("Generated file edited by hand").

---

## 2. Read, in this order

1. The diff itself, in full.
2. For a worker change: its `worker.py`, its `config.py`, and the pipeline role the change sits in
   (`packages/trellis-events/src/trellis_events/pipeline/roles.py` names the four).
3. `standards/python.md` — the rule list. Keep it open; cite rule titles in findings.
4. Only when the change adds a worker, a CLI command or a config field: the matching section of
   `../../AGENTS.md` ("Workers", "Adding a CLI command", "Configuration, environment, secrets"),
   which lists the edit points a change of that kind must touch. A missing edit point is a
   finding.

---

## 3. Check mechanically what can be checked mechanically

Do not reason about what a command can answer:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy                    # strict, plus disallow_any_explicit
uv run pytest                  # tooling + contract tests (integration deselected)
uv run pytest -m integration   # real containers; needs Docker
```

These are exactly the commands `.gitlab-ci.yml` runs, from the repo root. A change to an event
schema is not made here at all: `contracts-snapshot/` is a read-only mirror of trellis-backend's
`contracts/` (see [`contracts-snapshot/README.md`](../../contracts-snapshot/README.md)), refreshed
with `scripts/update-contracts-snapshot.sh`.

ruff already bans `os.environ` / `os.getenv` outside `env_vars.py`, `print`, `freezegun` and the
rest of the banned API list; mypy already catches `Any` and missing annotations. If those pass, do
not file them — review what they cannot see: whether the action is genuinely idempotent, whether a
failure is permanent or retryable, whether a secret reaches a log, whether the inbox key is right.

---

## 4. Report

One section per finding, nothing else:

```text
### <Rule title from standards/python.md>
<path>:<line>
What is wrong, in one or two sentences. Then the fix, concretely.
Severity: blocking | high | medium
```

- **blocking** — a secret that can be logged or put in a URL, a non-idempotent side effect, an
  acknowledgement before the DLQ write, a renamed `consumer_name`, an edited generated file.
- **high** — would fail a gate, or breaks a rule with a runtime consequence (an env var read
  outside `env_vars.py`, a retryable error raised as `PermanentError` or the reverse).
- **medium** — a real rule break with no runtime consequence yet (an f-string log message, a
  `TypedDict` outside tests, a dependency added to the workspace root).

Rules: cite `file:line`; quote the offending line when it is short; never file a finding that ruff
or mypy already reports; if the diff is clean, say so and name what you checked. Do not ask for
feature tests — `../../AGENTS.md` "Testing (decision T5)" says they are deliberately not written
yet; tooling, contract and integration tests are the exception.
