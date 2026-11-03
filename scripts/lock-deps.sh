#!/usr/bin/env bash
# Regenerate the hash-locked dependency files from the version ranges.
#
#   backend/requirements.txt      ranges for the app (edit these)
#   backend/requirements-dev.txt  ranges for the test tools (edit these)
#   backend/requirements.lock     exact versions + hashes: the Docker image installs this
#   backend/requirements-dev.lock the same versions plus the test tools: CI installs this
#
# The image and CI install only the lock files, so a new release of any package reaches
# production only through a commit that regenerates them and passes the tests.
# Needs uv (https://docs.astral.sh/uv/). Resolves for Python 3.11 (the image) and later,
# so CI on 3.12 installs the same versions.
set -euo pipefail
cd "$(dirname "$0")/.."

uv pip compile backend/requirements.txt \
  --universal --python-version 3.11 --generate-hashes --no-header \
  -o backend/requirements.lock "$@"
uv pip compile backend/requirements-dev.txt \
  --universal --python-version 3.11 --generate-hashes --no-header \
  -c backend/requirements.lock \
  -o backend/requirements-dev.lock

echo "Locked. Review the diff, run the tests, and commit both .lock files."
