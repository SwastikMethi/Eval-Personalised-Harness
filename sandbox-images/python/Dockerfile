# Agent sandbox: python + git + mini-SWE-agent (eng review 3A — the harness
# lives INSIDE the sandbox so its shell commands are jailed and its only
# network path is the model proxy).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git coreutils \
    && rm -rf /var/lib/apt/lists/*

# Pin the harness; bump deliberately after re-running preflight.
RUN pip install --no-cache-dir "mini-swe-agent==1.14.0"

RUN useradd -u 1000 -m sandbox \
    && git config --system safe.directory '*'

USER 1000
WORKDIR /workspace
