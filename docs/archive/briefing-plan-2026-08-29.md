# Quack — Implementation Plan

Generated 2026-08-29. Foundation (config, SDK connectivity, Notion auth) is built and verified.

## Goal

One command produces a dated Markdown briefing containing:

1. **From the Crucible** — Claude's summary of a prose Notion page
2. **Rituals** — today's Agons rows, grouped by Code, with done state

## Design decisions

| Decision | Rationale |
|---|---|
| Rituals are rendered by plain Python, no LLM | A filter and a group-by are deterministic. An LLM here would be slower, cost money, and could get it wrong. |
| Crucible is summarized by Claude | Condensing unstructured prose is the one job the model does better than code. |
| Output is a Markdown file, not stdout | Notion's `Done` checkbox is reset daily and keeps no history. Dated files are the archive. |
| No `tools/`, no `agent.py` | There is no agent loop and no tool-calling. One `messages.create` call is the entire LLM surface. |

## Verified API facts

Confirmed against the live API on 2026-08-29 — do not re-derive:

| Fact | Value |
|---|---|
| Query verb | `POST /v1/data_sources/{id}/query` — **`PATCH` returns 400**, despite what the docs page renders |
| `Notion-Version` | `2026-03-11` |
| Agons data source | `a23b7da0-e8f4-4a21-a648-e810261410a0` |
| Search returns | `page` and `data_source` objects — never `database` |
| TLS | Local antivirus MITMs certs; `truststore.inject_into_ssl()` in `config.py` is load-bearing |

### Agons schema

| Property | Type | Values |
|---|---|---|
| `Ritual` | title | task name |
| `Code` | select | SE, ARABIC, GUITAR, DARBUKA, THEO, SPREE, SAGE, BIBLES, DATE, LING, OMSCS, BLEND, LEAD |
| `Day(s) of the Week` | multi_select | Everyday, Every Weekday, Mon–Sun |
| `Done` | checkbox | reset manually via the "Reset Agons" button |

## Target structure

```
quack/
├── __init__.py
├── __main__.py          # CLI entry: python -m quack
├── config.py            # DONE
├── agons.py             # fetch, filter to today, group by Code
├── crucible.py          # fetch page text, summarize via Claude
├── briefing.py          # render Markdown, write dated file
├── prompts/
│   └── crucible_summary.md
└── integrations/
    ├── __init__.py
    └── notion.py        # raw API calls only, no Quack logic

briefings/               # output, gitignored
tests/
├── test_agons.py
└── test_briefing.py
```

**Delete** `quack/tools/`, `quack/agent.py`, `quack/prompts/system.md` — artifacts of a tool-calling design that was not chosen.

## The day-selection rule

A ritual belongs to today when `Day(s) of the Week` contains **any** of:

- `Everyday`
- today's three-letter name (`Mon`…`Sun`)
- `Every Weekday`, **and** today is Mon–Fri

Push this to Notion as an `or` filter rather than fetching everything and
filtering client-side:

```json
{"filter": {"or": [
  {"property": "Day(s) of the Week", "multi_select": {"contains": "Everyday"}},
  {"property": "Day(s) of the Week", "multi_select": {"contains": "Thu"}},
  {"property": "Day(s) of the Week", "multi_select": {"contains": "Every Weekday"}}
]}}
```

Omit the `Every Weekday` clause on Sat/Sun. Keep `select_for_today()` as a pure
function anyway so the rule is unit-testable without network access.

## Milestones

### 1. `integrations/notion.py` — raw client

```python
def query_data_source(data_source_id: str, filter_: dict | None = None) -> list[dict]
def get_page_blocks(page_id: str) -> list[dict]
def blocks_to_text(blocks: list[dict]) -> str
```

Must follow pagination: the response carries `has_more` and `next_cursor`; pass
`start_cursor` until exhausted. Raise on non-200 with the response body included —
Notion's error messages are specific and worth surfacing.

`blocks_to_text` flattens `paragraph`, `heading_1/2/3`, `bulleted_list_item`,
`numbered_list_item`, and `to_do` by joining their `rich_text[].plain_text`.
Ignore unknown block types rather than failing.

### 2. `agons.py` — today's rituals

```python
def fetch_today(today: date) -> list[dict]        # calls query_data_source
def select_for_today(rows: list[dict], today: date) -> list[dict]   # pure
def group_by_code(rows: list[dict]) -> dict[str, list[dict]]        # pure
```

Normalize each row to `{"ritual": str, "code": str, "done": bool}` at this
boundary so nothing downstream touches Notion's nested property shapes.
Rows with no Code should land under `"—"` rather than crash.

### 3. `briefing.py` — render and write

```python
def render(today: date, groups: dict, crucible: str | None) -> str
def write(markdown: str, today: date) -> Path       # briefings/YYYY-MM-DD.md
```

`crucible=None` omits that section entirely, so v1 ships before Crucible access
is sorted. Show counts in the heading (`14 rituals, 3 done`) and render done
state as `[x]` / `[ ]`.

### 4. `__main__.py` — ship v1

Wire 1–3, print the written path. **This is a working tool** — stop here and use
it for a few days before adding Crucible.

### 5. `crucible.py` — blocked on access

```python
def fetch_text(page_id: str) -> str
def summarize(text: str) -> str
```

`summarize` makes one `client.messages.create` call using
`config.anthropic_client()` and the prompt in `prompts/crucible_summary.md`.
Keep the prompt in the file, not inline, so it can be tuned without code edits.
Return `None` on API failure and let the briefing render without the section —
a Crucible outage must not cost you the ritual list.

### 6. Wire Crucible into the briefing

Pass the summary into `render()`. Done.

## Testing

Unit-test the pure functions only; they hold all the logic worth protecting:

- `select_for_today` — Everyday, single-day match, Every Weekday on Wed vs Sat, no match
- `group_by_code` — grouping, missing Code, stable ordering
- `render` — with and without a Crucible section, done/undone rendering

Build fixtures by saving one real Notion response to `tests/fixtures/agons.json`.
Do not mock the Notion API in unit tests; the smoke tests already cover the live path.

## Blockers and open items

1. **Crucible access is not granted.** Search returns 0 hits. Grant its real
   source page via my-integrations → Content access, then confirm whether it is
   one page or several. Milestones 5–6 cannot start until then.
2. **Crucible's page ID is unknown** — determine it after access, add to `config.py`.
3. **Eons, Athlon, Constellations** are also invisible. Out of scope unless you
   want them.
4. **Add `briefings/` to `.gitignore`** before the first run.
