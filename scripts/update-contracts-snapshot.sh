#!/usr/bin/env sh
# Refresh contracts-snapshot/ from a local trellis-backend checkout.
#
# This script exists only for the transition described in contracts-snapshot/README.md. Once
# trellis-backend's CI publishes the `trellis-contracts` package to the GitLab Package Registry
# (decision T22), this repo installs that package and this script, together with
# contracts-snapshot/, is deleted. Nothing in CI calls it: refreshing the mirror is a deliberate,
# reviewed change, not something a pipeline does behind your back.
#
#   scripts/update-contracts-snapshot.sh
#   scripts/update-contracts-snapshot.sh --from /path/to/trellis-backend/contracts
set -eu

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$repo_root/../trellis-backend/contracts"

while [ $# -gt 0 ]; do
  case "$1" in
    --from) source_dir=${2:?--from needs a path}; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f "$source_dir/events/envelope.schema.json" ]; then
  echo "not a contracts/ directory: $source_dir" >&2
  exit 66
fi

target="$repo_root/contracts-snapshot"
for part in events examples testdata; do
  rm -rf "${target:?}/$part"
  cp -R "$source_dir/$part" "$target/$part"
done

commit=$(git -C "$source_dir" rev-parse HEAD 2>/dev/null || echo unknown)
{
  echo "Mirror of trellis-backend/contracts (events, examples, testdata)."
  echo "source commit: $commit"
  echo "copied at:     $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Do not edit the files here; see contracts-snapshot/README.md."
} > "$target/SOURCE.txt"

echo "contracts-snapshot updated from $source_dir ($commit)"
