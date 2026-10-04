# Quack — Progress

**Plan:** docs/PLAN.md
**Last touched:** 2026-10-04

## Phase 1 — The hand-rolled tool loop  [code complete, checkpoints owed]
- [~] 1.1 One question, one tool, end to end — autopilot — verified live; **checkpoint NOT done**
- [~] 1.2 A Notion client that respects the limit — AJ started a sidekick draft, then switched to autopilot; Claude wrote it — 3 req/s limiter, Retry-After, partial results; **checkpoint NOT done**
- [~] 1.3 Trace events from the first line — autopilot — traces/quack.jsonl; **checkpoint NOT done**

## Phase 2 — Port to LangChain, add tools and a UI  [not started]
## Phase 3 — Multi-step reasoning under a budget  [not started]
## Phase 4 — Hybrid retrieval with Chroma  [not started]

## Code written by Claude
- 1.1: `quack/agent.py` loop body
- 1.2: `quack/integrations/notion.py` (RateLimiter, _request, _paginate, NotionResults, stats); `search_notion` now returns {"results", "partial", "warning"}; config constants
- 1.3: `quack/tracing.py`, tracing wired into `agent.ask`
- tests: `tests/test_tools.py`, `tests/test_client.py`, `tests/fixtures/search.json`
- `scripts/smoke_test.py` model ID aligned to config.MODEL

## Deviations from the plan
- Phase 1 was completed in autopilot; the learning intent of 1.2/1.3 now rests on the checkpoints.

## Carryover
- Checkpoints owed (AJ): 1.1 Mermaid redraw + "who opens the connection to api.notion.com / what is appended to messages"; 1.2 burst at 10 req/s, predict 429 count and tool_result; 1.3 reconstruct one question and its cost from traces/quack.jsonl alone.
- AJ's own 1.2 draft is saved at `.claude/backup/notion.py.aj-draft-1.2`.
- Run with `.venv\Scripts\python.exe` (system python lacks packages).
- `AJ_GEBARA_PAGE_ID` ranking in `search_notion` never fires on live data (0 of 1,016 results are direct children). Decide before 2.2.
- CLAUDE.md "Current status" is stale; update when checkpoints pass.
