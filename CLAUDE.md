# Quack

A read-only agent that answers questions about AJ's Notion workspace. It uses Claude tool use, then LangChain (Phase 2 onward), then hybrid live/RAG retrieval (Phase 4). Python backend, with a React/TS chat UI arriving in Phase 2.

**Source of truth: `docs/PLAN.md`** (mirrored on the "Build Quack" Odyssey page in Notion). It holds the phases, milestones, checkpoints, architecture decisions and both Mermaid diagrams. Read it before starting any milestone. `docs/archive/briefing-plan-2026-08-29.md` is the superseded daily-briefing design, kept only for its verified API facts, which are copied below. Do not follow its instructions to delete `agent.py` or `tools/`.

## How to work with AJ here: sidekick mode by default

This is a learning project, so how Claude helps matters as much as what gets built.

- **AJ writes the learning-critical code.** That means the agent loop (`agent.py`), tool schemas and handlers (`quack/tools/`), the Notion client's rate limiter, retry and pagination logic, the tracer, and later the LangChain port, router and indexer. For these, Claude names the file, the function signature and where it goes, and explains the concept. Claude does not write the body.
- **Override:** if AJ says "you write this one", Claude writes it. The override covers that piece only.
- **Fair game for Claude without asking:** scaffolding, `__init__.py` files, config constants, requirements, `.gitignore`, tests (fixtures and cases, not limited to pure functions — AJ doesn't need to write tests), and docs.
- **Reviewing AJ's code:** point at the line and say what's wrong and why. Suggest the direction of the fix and let AJ make it. Don't paste a rewritten version.
- **At a milestone boundary:** name the checkpoint from `docs/PLAN.md` and have AJ do it before moving on. Don't mark a milestone done because the code runs.
- **Scope:** don't pull later phases forward. No LangChain before Phase 2, no FastAPI or UI before Milestone 2.3, no Chroma or embeddings before Phase 4.

## Current status

Phase 1, Milestone 1.1 (hand-rolled tool loop).

- Done: `quack/config.py`, `scripts/smoke_test.py` (Anthropic), `scripts/notion_smoke_test.py` (Notion auth and visibility).
- In progress: `query_data_source` in the stray top-level `integration/notion.py`. It belongs in `quack/integrations/notion.py`, and `integration/` should go once it's moved. Known gaps: no pagination, it prints and returns `[]` on errors instead of raising, `import config` should be `from quack import config`, and the stubs call `NotImplemented()` instead of `raise NotImplementedError`.
- Empty: `agent.py`, `tools/`, `__main__.py`, `prompts/system.md`, `tests/`.
- Unverified: `MODEL` in `config.py`. Anthropic model IDs use hyphens, so confirm it with the smoke test.

Update this section when a milestone closes.

## Layout (Phase 1 target)

```
quack/
  __main__.py            # python -m quack "question"  -> prints answer
  config.py              # constants + clients; the only place IDs and the model name live
  agent.py               # hand-rolled tool_use -> tool_result loop
  tracing.py             # JSONL trace events (Milestone 1.3)
  prompts/system.md      # prompts live in files, never inline
  tools/                 # tool schemas + handlers; registry in __init__.py
  integrations/notion.py # raw Notion HTTP only: limiter, retry, pagination. No Quack logic.
scripts/                 # smoke tests, not part of Quack
tests/                   # pure-function unit tests + fixtures
traces/                  # trace output (gitignore it)
```

**The main boundary:** tools translate between Claude and Notion, and `integrations/notion.py` only speaks HTTP. Normalize Notion's nested property shapes into plain dicts at the tool boundary, so nothing downstream touches raw Notion JSON.

## Notion API facts (verified against the live API, do not re-derive)

| Fact | Value |
|---|---|
| Query | `POST /v1/data_sources/{id}/query`. `PATCH` returns 400, whatever the docs page shows. |
| `Notion-Version` | `2026-03-11` (pinned in `config.py`) |
| Search returns | `page` and `data_source` objects, never `database` |
| Pagination | responses carry `has_more` + `next_cursor`; pass `start_cursor` until exhausted |
| Rate limit | ~3 req/s average per integration; 429 carries `Retry-After`. One shared client enforces it for everything. |
| Access | a token sees nothing until each page/database is connected to the integration in Notion |
| TLS | local antivirus re-signs certs; `truststore.inject_into_ssl()` in `config.py` is load-bearing. Don't remove it. |
| Errors | raise on non-200 and include the response body, because Notion's error messages are specific |

### Agoge (formerly "Agons", renamed in Notion)

Use "Agoge" in all new code, names and prompts. The IDs are `AGOGE_DATA_SOURCE_ID` and `AGOGE_DATABASE_ID` in `config.py`. The rename did change the IDs (the pre-rename ones 404), and the integration only sees a database once it is shared with it in Notion. Schema re-verified against the live API on 2026-10-04:

| Property | Type | Values |
|---|---|---|
| `Ritual` | title | task name |
| `Ultimate` | relation | links to the Ultimates database (replaced the old `Code` select) |
| `Day(s) of the Week` | multi_select | full names only: Monday through Sunday (no `Everyday` / `Every Weekday` options) |
| `Done` | checkbox | reset manually each day |

A ritual belongs to today if `Day(s) of the Week` contains today's full weekday name (the filter is `{"property": "Day(s) of the Week", "multi_select": {"contains": "Sunday"}}`). The system prompt gets today's date injected from `quack/prompt.py`. "What are today's Agoge rituals?" is Quack's first eval question; on 2026-10-04 (a Sunday) the answer was 10 rituals, matching the filtered query.

The integration currently sees five databases: Agoge, Crucible, Inferno, Odysseys and Ultimates. The old legacy Odysseys (plus Horizons and Contribution Naming) was unshared from the integration on purpose, so there is exactly one Odysseys to find. If an old Odysseys ever reappears in search results, ignore it: the real one lives under the A.J. Gebara hub.

## Commands

```
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
python scripts/smoke_test.py            # Anthropic reachable, model ID valid
python scripts/notion_smoke_test.py     # token valid + which data sources it can see
python -m quack "question"              # hand-rolled loop
python -m quack --lc "question"         # LangChain agent
uvicorn quack.api:app --reload --port 8000   # chat API (POST /chat streams SSE)
cd ui && npm run dev                    # chat UI on :5173 (needs the API running)
                                        # UI stack: React+TS, Tailwind v4, Zustand, axios, @microsoft/fetch-event-source, TanStack Query
cd ui && npm run check                  # typecheck + oxlint + prettier + vitest
cd ui && npm run e2e                    # Playwright (mocked backend)
python -m pytest                        # add pytest to requirements first
```

## Conventions

- Python 3.10+ (`X | None` syntax). 4-space indent. Type hints on public functions.
- Secrets only in `.env` (gitignored). Never print or log keys.
- The model name and all Notion IDs live in `config.py` only.
- Read-only: Quack never writes to Notion in the MVP. No `PATCH`/`POST` to pages or blocks. Queries and search only.
- Unit-test pure functions with fixtures saved from real Notion responses (`tests/fixtures/`). Don't mock the Notion API. The smoke tests cover the live path.
- The repo has mixed CRLF/LF line endings. Keep a file's existing endings, and don't reformat whole files.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
