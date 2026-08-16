# Agent sandbox: python + git + mini-SWE-agent (eng review 3A — the harness
# lives INSIDE the sandbox so its shell commands are jailed and its only
# network path is the model proxy).
FROM python:3.12-slim

# Node alongside Python: spec §6 makes Python and JS/TS both first-class, and a
# JS repo cannot be baselined or evaluated at all without npm.
#
# make and build-essential are here rather than in the per-repo layer because
# almost every repo needs one of them: a repo whose install command is
# `make setup` failed with exit 127, and any dependency with a C extension
# (lxml, psycopg2, numpy from source) needs a compiler. Paying apt for those on
# every per-repo build would cost time and a network round trip each time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git coreutils curl ca-certificates make build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv is now a common Python installer, and `uv sync` is what the detector picks
# whenever a repo ships uv.lock — without the binary that command is exit 127.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# Pin the harnesses; bump deliberately after re-running preflight.
# Both run in-container so their shell/code execution is jailed and their only
# network path is the model proxy.
RUN pip install --no-cache-dir "mini-swe-agent==1.14.0" "smolagents==1.26.0"

RUN useradd -u 1000 -m sandbox \
    && git config --system safe.directory '*'

USER 1000
WORKDIR /workspace
