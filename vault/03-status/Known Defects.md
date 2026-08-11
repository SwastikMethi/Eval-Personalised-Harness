---
tags: [aso/status, aso/defect]
status: current
updated: 2026-08-11
---

# Known Defects

Seven defects found by reading code on 2026-08-11. **Each one blocks a real benchmark run.** Index: [[00 Index]].

Line references are to the state at branch `worktree-aso-full-build` creation; re-grep before trusting them.

---

## 1. The golden path is severed 🔴

`service.create_snapshot()` — the [[Leakage Prevention]] `git archive`-at-base-commit builder — is called **only** from `api/repos_analysis.py:157` during baseline validation. The queue never calls it.

`orchestration/queue.py:208` builds every agent workspace with:

```python
fixture = config.get("fixture_path")
if fixture:
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)
```

**Consequence:** historical replay does not actually work. A task carries `base_commit`, but the run ignores it and copies a raw directory.

**Blocks:** [[Acceptance Criteria]] #10, #11. **Fixed in:** [[Roadmap]] Phase 2.

---

## 2. Regression detection is dead on real repos 🔴

Nothing writes `baseline_cases` into experiment config — grep finds only *readers* (`queue.py:329`), no producer. `BaselineResult` rows exist but never reach a run.

**Consequence:** every regression check compares against an empty baseline, so regressions are invisible.

**Fixed in:** Phase 2.

---

## 3. Detected commands never reach runs 🟠

`RepositoryCommand` rows are populated by analysis, but `queue.py:327` falls back to a hardcoded `{"test": "pytest -v"}`.

**Consequence:** a JS/TS repo would be graded with pytest.

**Fixed in:** Phase 2.

---

## 4. Cost accounting is inert 🟠

`queue.py:212` calls `issue_run_token()` without `input_price` / `output_price`, so `entry.cost_usd` (`proxy.py:165-168`) never leaves `0.0` and the ceiling at `proxy.py:110` can never fire.

Free models make this $0 anyway — but §14 requires cost recorded even when zero, and this same path is the only guard on a future paid key.

**Fixed in:** Phase 3.

---

## 5. The proxy destroys tool calls 🔴

`proxy.py:180-195` returns a hand-built response containing only `message.content` and a hardcoded `finish_reason: "stop"`. `ChatRequest` (`proxy.py:139`) has no `tools` field, so tool definitions are dropped inbound and tool calls dropped outbound.

**Consequence:** smolagents survives (it parses code from content). **OpenHands cannot work at all.**

**Fixed in:** Phase 3 — prerequisite for Phase 10.

---

## 6. Rate limiting fails the run 🔴

The proxy maps 429 correctly, but `queue.py:175-177` catches *every* exception into `FAILED(HARNESS)`. Nothing ever transitions into `RATE_LIMITED`.

**Consequence:** violates [[Acceptance Criteria]] #24 — and under [[Rate Limits]] (~50 requests/day) this fires constantly, writing spurious `FAILED` rows that corrupt results.

**Fixed in:** Phase 3. **Must land before any real run.**

---

## 7. Broken developer targets 🟠

| Target | Failure |
|---|---|
| `make migrate` | `No 'script_location' key found` — `alembic` is a declared dependency but there is no `alembic/` or `alembic.ini` |
| `make seed` | `No module named app.seed` — only `app/demo.py` exists |
| `make test-frontend` | **False green.** `npm test --if-present` with no test script, no vitest, zero test files → exits 0 while testing nothing |

**Fixed in:** Phase 1.

---

## Severity key

🔴 blocks a correct benchmark result · 🟠 blocks correctness on real repos or lies about status

## Related

- [[Implemented]] · [[Spec Gaps]] · [[Roadmap]] · [[Acceptance Criteria]]
