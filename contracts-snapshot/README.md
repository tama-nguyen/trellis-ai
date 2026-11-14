# contracts-snapshot/ — temporary mirror, deleted when `trellis-contracts` is published

Decision **T22**: `contracts/` belongs to **trellis-backend**, which owns the event JSON Schemas and
exports the OpenAPI document. Backend CI generates the Python models and publishes them to the
GitLab Package Registry as the PyPI package **`trellis-contracts`**; this repo installs that package
instead of generating anything from local files.

That package does not exist yet. Until it does, this folder holds a read-only copy of the files this
repo needs at runtime and in tests, so the repo works on its own:

| Path | Used by |
| --- | --- |
| `events/envelope.schema.json`, `events/<eventType>/v<N>.schema.json` | `trellis_events.contract_validation`, `trellis events validate`, the worker's contract check |
| `examples/notice.published.v1.json` | `trellis worker run notice-stats --input ...`, envelope tests |
| `testdata/backoff.json`, `testdata/stable-id.json` | the vectors that must give the same results in Java and Python |

**Never edit a file here.** Change the schema in trellis-backend, then refresh the mirror:

```bash
scripts/update-contracts-snapshot.sh                     # from ../trellis-backend/contracts
scripts/update-contracts-snapshot.sh --from /path/to/trellis-backend/contracts
```

`SOURCE.txt` records which backend commit the current copy came from.

## What flips over when `trellis-contracts` is published

1. `pyproject.toml`: uncomment the `trellis-contracts==<version>` dependency and the
   `[[tool.uv.index]]` block for the GitLab Package Registry.
2. Delete this folder, `scripts/update-contracts-snapshot.sh`, and `TRELLIS_CONTRACTS_DIR` defaults
   that point here (`tests/support.py`, `Dockerfile`, `.gitlab-ci.yml`); the schemas ship as package
   data inside `trellis_contracts`.
3. Delete `packages/trellis-events/src/trellis_events/generated/` and
   `packages/trellis-sdk/src/trellis_sdk/generated/`, and import the models from `trellis_contracts`
   instead (`trellis_events.envelope` and `trellis_sdk.client` are the only two places that need to
   change: everything else imports through them).
