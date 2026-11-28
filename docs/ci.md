# GitHub build verification

The workflow is `.github/workflows/ci.yml`. PRs, pushes to `main` and merge queues run the full
gate. Manual **Actions → CI → Run workflow** exposes boolean `run_tests` (default `true`).
Set it to `false` for a build without tests; static checks and packaging still run.

Tool versions come from `mise.toml` and existing package manifests. Action dependencies are pinned
by full SHA and updated weekly by Dependabot. Jobs use Ubuntu hosted runners, a read-only token,
checkout without persisted credentials, cancellation of superseded PR runs and bounded timeouts.

No registry login, image push, package publication or deployment is configured. Docker images are
built on the runner and discarded afterwards. Reports/artifacts are retained for seven days.

## Enable in GitHub

1. Enable Actions in repository settings and permit the pinned `actions/*` and `jdx/mise-action`
   actions. Use read-only workflow permissions. No repository secret is required.
2. Merge the workflow into the default branch so **Run workflow** appears.
3. Run with tests enabled, then require the job's check in the main branch ruleset.
4. Review Dependabot updates to maintain action pins.

## Python checks

**Python build** checks `uv.lock`, installs with `uv sync --locked`, runs Ruff format/lint and strict
mypy, runs tooling/contract pytest with coverage, and runs the existing PostgreSQL integration
suite on the runner's local Docker daemon. It then builds every workspace distribution and the
notification-stats worker image.

`run_tests=false` skips both pytest runs. Lockfile, formatting, lint, types, wheel/sdist and Docker
build checks still execute. Artifacts include coverage, JUnit reports and workspace distributions.

Sources: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[uv integration with GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/).
