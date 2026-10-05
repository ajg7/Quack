# Quack UI

React + TypeScript chat UI for the Quack backend.

| Concern       | Choice                                                                                                                                                                             |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Build         | Vite, React 19, TypeScript                                                                                                                                                         |
| Styling       | Tailwind CSS v4 (`@tailwindcss/vite`); design tokens in `src/styles/tokens.css`, mapped to utilities in `src/index.css` (`bg-surface`, `text-ink`, `rounded-card`, `bg-yolk`, ...) |
| Chat state    | Zustand (`persist` middleware keeps the session id in `sessionStorage`)                                                                                                            |
| REST calls    | axios (instance with the `fetch` adapter)                                                                                                                                          |
| Streaming     | `@microsoft/fetch-event-source` (POST + SSE)                                                                                                                                       |
| Server state  | TanStack Query (health, sources)                                                                                                                                                   |
| Lint / format | oxlint, Prettier (double quotes, Tailwind class sorting)                                                                                                                           |
| Tests         | Vitest + React Testing Library + jsdom, Playwright                                                                                                                                 |

```
npm install
cp .env.example .env     # optional; defaults to http://localhost:8000
npm run dev              # http://localhost:5173 (the backend's CORS allows this origin)
```

Scripts: `typecheck`, `lint`, `lint:fix`, `format`, `format:check`, `test`, `e2e`, `build`, `check`.
The backend must be running: `uvicorn quack.api:app --reload --port 8000` from the repo root.

Not installed on purpose: TanStack Hotkeys. Its README says it is alpha (0.x, no 1.0 yet); revisit when it stabilizes.
