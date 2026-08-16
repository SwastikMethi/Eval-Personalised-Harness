# Agent sandbox: python + git + mini-SWE-agent (eng review 3A — the harness
# lives INSIDE the sandbox so its shell commands are jailed and its only
# network path is the model proxy).
FROM python:3.12-slim

# Node alongside Python: spec §6 makes Python and JS/TS both first-class, and a
# JS repo cannot be baselined or evaluated at all without npm.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git coreutils curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Pin the harnesses; bump deliberately after re-running preflight.
# Both run in-container so their shell/code execution is jailed and their only
# network path is the model proxy.
RUN pip install --no-cache-dir "mini-swe-agent==1.14.0" "smolagents==1.26.0"

RUN useradd -u 1000 -m sandbox \
    && git config --system safe.directory '*'

USER 1000
WORKDIR /workspace
