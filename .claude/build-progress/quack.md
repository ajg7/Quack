# Quack — Progress

**Plan:** docs/PLAN.md
**Last touched:** 2026-10-04

## Phase 1 — The hand-rolled tool loop  [code complete, checkpoints SKIPPED]
- [~] 1.1 One question, one tool, end to end — autopilot — verified live; **checkpoint SKIPPED**
- [~] 1.2 A Notion client that respects the limit — AJ started a sidekick draft, then switched to autopilot; Claude wrote it — 3 req/s limiter, Retry-After, partial results; **checkpoint SKIPPED**
- [~] 1.3 Trace events from the first line — autopilot — traces/quack.jsonl; **checkpoint SKIPPED**

## Phase 2 — Port to LangChain, add tools and a UI  [starting]
- [~] 2.1 Parity port — started sidekick (guided), AJ asked Claude to implement -> autopilot — `python -m quack --lc "q"`; parity verified (1,811 in / same events); **checkpoint SKIPPED**
- [~] 2.2 Three tools Claude chooses between well — started sidekick (guided); AJ asked Claude to implement steps 2-8 -> autopilot — code complete, live-verified on 2 questions; **checkpoint (8 questions) NOT done**
- [~] 2.3 Streaming chat with progress — autopilot, **backend done** (FastAPI + SSE + sessions + tests, live-verified); **UI half: AJ is writing it in sidekick mode (guided, snippets in chat).** Claude set up ui/ boilerplate only (Vite + React 19 + TS, TanStack Query, react-markdown, oxlint + Prettier (double quotes), Vitest + React Testing Library + jsdom, Playwright). Reference implementation built and verified OUTSIDE the repo at %TEMP%\quack-ui-ref (38 unit/component tests, 5 mocked e2e, 2 real-backend e2e incl. killing the backend mid-answer). Checkpoint (kill backend mid-answer, make the UI say something true) not done by AJ

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
- UI stack (AJ's choices, 2026-10-04): Zustand (not Context) for chat state, axios (fetch adapter) for REST, @microsoft/fetch-event-source for the SSE stream (NOT plain fetch), TanStack Query for health/sources, Tailwind v4, oxlint + Prettier (double quotes), Vitest + RTL + Playwright. Design source of truth: the "Quack" Design artifact https://claude.ai/artifact/8niCsJCSw7SnHQsGgsSoGz (brand, Chat light/dark, Favicon, Traces, Banner). Chat screen implemented against it in the reference; Trace viewer + ritual checkbox cards NOT built (Nexus UI is out of MVP; Quack is read-only).
- Also installed: @tanstack/react-form 1.33.5 (stable) and zod 4.6.5. @tanstack/react-hotkeys NOT installed: README says 'alpha', version 0.13.0, no 1.0 (checked 2026-10-04). zod validates SSE payloads/API responses and is the Form validator; note zod issues in `field.state.meta.errors` are objects, map `.message`.
- Backend additions for the UI: progress events now carry `args`; GET /sources lists shared databases (502 on Notion failure).
- fetch-event-source gotchas: set openWhenHidden:true (else hiding the tab re-POSTs the question); provide onerror that throws (else it retries forever); abort RESOLVES the promise (check signal.aborted). axios fetch adapter passes a Request object to fetch (test mocks must normalize) and caches the first fetch it sees.
- ui/ tooling notes: repo path contains '&' so npm scripts call tools via `node node_modules/<pkg>/...` (shims break); Playwright workers=1 (parallel Chromium launches hang on this machine); lint is oxlint (not ESLint), double quotes enforced by Prettier. Scripts: dev, build, typecheck, lint, format, format:check, test, e2e, check.
- Finding: no timeout on the LLM call. A hung upstream request makes /chat send only `ping`s for up to the Anthropic client default (10 min); UI would sit on 'Thinking...'. Consider ChatAnthropic(timeout=...) / max_retries and a step budget (Phase 3).
- A uvicorn started via PowerShell Start-Process (hidden) hung on the agent call while the same server started from bash worked; undiagnosed.
- Phase 2 is NOT complete: UI half of 2.3 remains, so no phase commit/push yet. Commit policy: per phase. Repo ajg7/Quack is PUBLIC; user pushes to main directly; plan: branch first, exclude tests/fixtures/{search,odysseys_rows}.json (real workspace data) and make dependent tests skip, include CLAUDE.md.
- Integration now sees 5 data sources (Agoge, Crucible, Inferno, Odysseys, Ultimates); legacy Odysseys/Horizons/Contribution Naming were unshared. Agoge IDs in config.py updated (old ones 404'd). tests/fixtures/odysseys_rows.json and search.json still hold the OLD legacy Odysseys rows.
- 2.3 backend: quack/api.py (POST /chat SSE, GET /health, DELETE /sessions/{id}, CORS for Vite :5173), quack/streaming.py (StreamHandler + stream_events, worker thread + queue, keepalive pings, cancel on disconnect), quack/sessions.py (in-memory, 20-message cap), agent_lc.run()/RunResult. SSE events: start, progress{status,step,tool,message}, token{text}, done{answer,usage...}, error{message}, ping.
- UI contract for later: a stream that ends without `done` or `error` means the backend died; the UI must say so truthfully (2.3 checkpoint).
- Commit/push policy (AJ, 2026-10-04): commit and push after each PHASE, not each step. Phase 1 code was already committed by AJ. Before the first push: repo is on main (branch first?), gh CLI not installed, and tests/fixtures/{search,odysseys_rows}.json contain real workspace data (check repo visibility).
- 2.2 finding: search_notion returns every match (21k chars on 'Train for the Agoge' -> ~29k input tokens). Consider a result cap; log as a tool-design/cost observation for the checkpoint.
- 2.2 code by Claude: tools/notion.py (query_database, get_page, normalize_properties/normalize_row), config constants, tools/__init__.py registry, agent_lc.py tool loop, prompts/system.md, tests (test_normalize, test_query_tools).
- 2.2 live-API findings: Agoge data source (config.AGOGE_DATA_SOURCE_ID) returns 404 for the Quack integration; it only sees Odysseys, Horizons, Contribution Naming. Odysseys has >100 rows (select equals October alone exceeds one page), so query_database needs a limit. search_notion results lack `id`, which the new tools need.
- 2.1 finding for the checkpoint: LangChain's default crashes the run when a tool raises; the hand-rolled loop returned is_error to Claude. Fixed with ToolException + handle_tool_error=True in agent_lc.py.
- Code written by Claude in 2.1: quack/agent_lc.py, quack/tracing_lc.py, `--lc` flag in __main__.py, tests/test_lc.py. AJ's own scaffolding (tool wrapper, file split) kept.
- AJ's mode for Phase 2 onward: sidekick with hand-holding (new to agents). Snippets in chat on request. langchain 1.4.3 + langchain-anthropic 1.7.5 installed and probed; `create_agent` + `BaseCallbackHandler` verified against search_notion.
- AJ chose to move to Phase 2 on 2026-10-04 and asked Claude to "just do" the checkpoints; Claude declined to pass them for him, so all three are logged as skipped. Still available as retention practice: 1.1 Mermaid redraw + "who opens the connection to api.notion.com / what is appended to messages"; 1.2 burst at 10 req/s, predict 429 count and tool_result; 1.3 reconstruct one question and its cost from traces/quack.jsonl alone.
- AJ's own 1.2 draft is saved at `.claude/backup/notion.py.aj-draft-1.2`.
- Run with `.venv\Scripts\python.exe` (system python lacks packages).
- `AJ_GEBARA_PAGE_ID` ranking in `search_notion` never fires on live data (0 of 1,016 results are direct children). Decide before 2.2.
- CLAUDE.md "Current status" is stale; update when checkpoints pass.
