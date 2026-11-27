"""Paths shared by tests. Tests never depend on the working directory."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# The backend's contracts, mirrored here until the `trellis-contracts` package exists (decision
# T22); contracts-snapshot/README.md says what changes then.
CONTRACTS_DIR = REPO_ROOT / "contracts-snapshot"
EXAMPLE_ENVELOPE = CONTRACTS_DIR / "examples" / "notification.published.v1.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
INVALID_ENVELOPE = FIXTURES / "invalid-notification.published.v1.json"
