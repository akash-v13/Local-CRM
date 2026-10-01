# Frontend

React 19 + TypeScript, built with Vite. Two areas:

| Route | What |
|---|---|
| `/webform` | **Test webform**: stands in for the contact form a business embeds on its website. Submitting creates a real case. |
| `/cases` | **Agent console**: case list, filterable by status. |
| `/cases/:caseId` | **Case view**: conversation, reply box, customer and case details, queue (reroute), status buttons, history. |
| `/ops` | **Operations Portal: dashboard**: open cases, where they're waiting, queue × status table. |
| `/ops/queues` | **Operations Portal: queues** in routing order; activate/deactivate. |
| `/ops/queues/new`, `/ops/queues/:id` | **Queue editor**: name, priority, match conditions, handling settings, live routing test. |

## Everyday commands

Run from this `frontend/` folder. (Or skip all of this and use `docker compose up`, which runs the UI for you at http://localhost:5173.)

| Task | Command |
|---|---|
| Install dependencies | `npm install` |
| Dev server (needs the API on :8000) | `npm run dev` → http://localhost:5173 |
| Tests | `npm test` |
| Type check | `npm run typecheck` |
| Production build | `npm run build` |

## How it talks to the backend

The UI calls `/api/...`. Vite forwards those requests to FastAPI and removes the `/api` prefix (`vite.config.ts`):

```
browser → http://localhost:5173/api/tenants → (Vite proxy) → http://localhost:8000/tenants
```

Because the browser only ever talks to one origin, no CORS configuration is needed. In Docker, the proxy target is `http://api:8000` (set by `API_TARGET` in docker-compose).

## Where things are

```
src/
├── main.tsx              Entry point
├── App.tsx               Routes
├── styles.css            All styles; colors are CSS variables (light + dark mode)
├── api/
│   ├── types.ts          TypeScript mirrors of the backend schemas
│   └── client.ts         The ONLY code that calls the backend (fetch wrapper + ApiError)
├── context/
│   └── SessionContext    Current tenant + "acting as" agent (no login yet)
├── lib/
│   ├── useLoad.ts        Hook: load data with loading/error state and reload()
│   ├── format.ts         Status labels, date/age and category formatting
│   └── criteria.ts       Queue rules ⇄ editor form state, plain-language summaries
├── components/           Reusable pieces (each file has a comment explaining it)
│   ├── Layout            Top bar + page outlet
│   ├── TenantPicker      Dev tenant switcher / creator
│   ├── Field             Label + input, correctly linked for accessibility
│   ├── CategorySelect    Type → Category → Subcategory dropdowns
│   ├── MessageThread     Conversation view
│   ├── ReplyComposer     Reply / internal note / simulate-customer box
│   ├── StatusActions     Buttons for the allowed next statuses
│   ├── EventTimeline     Audit trail
│   ├── StatusBadge       Status pill
│   ├── QueueCard         Case's queue: run routing again / move to another queue
│   ├── ConditionBuilder  Queue match-rule editor (field · operator · value rows)
│   ├── RoutingPreviewPanel  "Which queue would this case land in?" test
│   ├── StatTile          Headline number (KPI)
│   └── QueueHeatTable    Queue × status counts, shaded by volume
├── pages/                One file per route
│   └── ops/              Operations Portal pages (layout, dashboard, queue list, queue editor)
└── test/                 Test setup and fixtures
```

## Conventions

- **All backend calls go through `api` in `src/api/client.ts`.** Components never call `fetch` directly, which keeps them easy to test (tests replace `api` with spies).
- **The backend decides what's allowed.** For example, status buttons come from `allowed_next_statuses`, so the UI can't offer a move the lifecycle forbids. Show the backend's error `detail` when something is rejected.
- **After a change, reload** the affected data (`reload()` from `useLoad`) rather than patching local state by hand. That's simple and always correct. Optimize later if needed.
- **Types mirror `backend/app/schemas.py`.** Change both together. Once the API grows, generate `types.ts` from http://localhost:8000/openapi.json.
- **Colors come from CSS variables** in `styles.css` (`var(--accent)` etc.), so dark mode works automatically.
- **Form fields use `<Field>`** so labels are linked to their inputs.

## Tests

Component tests use Vitest + Testing Library and run in a simulated browser (jsdom). They mock the `api` module, so no backend is needed:

- `CategorySelect.test.tsx`: dropdowns enable in order and reset lower levels
- `ReplyComposer.test.tsx`: correct message kind sent, "Send & mark solved" only when allowed, closed cases only accept notes, backend errors shown
- `StatusActions.test.tsx`: one button per allowed status, sends the agent and reason
- `ConditionBuilder.test.tsx`: builds all/any rules row by row, flags incomplete rows
- `QueueHeatTable.test.tsx`: every count links to the right filtered case list; shading by volume
- `TenantPicker.test.tsx`: a new tenant is selected immediately and stays selected
- `lib/criteria.test.ts`: rule ⇄ form round-trip, validation, summaries

## Charts and color

The dashboard follows the data-visualization method used for this project:
headline numbers are **stat tiles** (not charts), and the queue × status grid is
a **table with ordinal shading**, a single blue ramp in 5 steps, darker = more
open cases. The number is always printed, so shading is never the only signal,
and every count is a link. The ramp is defined as CSS variables (`--heat-1…5`)
with separate light and dark steps, and both were checked with the palette
validator (single hue, monotone lightness, visible steps, lightest step clears
the background).

## Temporary / development-only pieces

These exist to make testing possible before the real features exist:

| Piece | Replaced by |
|---|---|
| Tenant picker in the top bar | Sign-in; tenant comes from the user's account |
| "Acting as" field | Sign-in; agent identity comes from the user's account |
| "Simulate customer reply" tab | Real inbound email / webform replies |
| Manual status buttons | Enrichment, queue matching and the AI agent moving cases automatically |
| "Sent · simulated" replies | A real email connector |
