# Frontend

React 19 + TypeScript, built with Vite. Two areas:

| Route | What |
|---|---|
| `/webform` | **Test webform**: stands in for the contact form a business embeds on its website. Submitting creates a real case. |
| `/cases` | **Agent console**: case list, filterable by status. |
| `/cases/:caseId` | **Case view**: conversation, reply box, customer and case details, queue (reroute), status buttons, history. |
| `/ops` | **Operations Portal: dashboard**: open cases, where they're waiting, queue × status table. |
| `/ops/queues` | **Operations Portal: queues** in routing order; activate/deactivate. |
| `/ops/queues/new`, `/ops/queues/:id` | **Queue editor**: name, priority, match conditions, handling settings (incl. AI model and effort), live routing test. |
| `/ops/connectors`, `/ops/connectors/new`, `/ops/connectors/:id` | **Connectors**: API calls that enrich cases. The editor is laid out as steps: Basics → Request → Authentication → Test & pick fields → Fields to keep → When to run → Order & reliability. |
| `/ops/templates` | **Prompt templates**: the four layers (locked platform rules → baseline → queue persona → case type), which template each queue and category uses, and **New template**. |
| `/ops/templates/<name>` (e.g. `/ops/templates/category/Complaint_Delivery.jinja`) | **Template editor**: Jinja source with clickable variables, checks, live **preview** on a case, download/upload `.jinja`, **test lab**, **cost projection**, **version history**. |
| `/ops/compensation`, `/ops/compensation/new`, `/ops/compensation/:id` | **Compensation**: rules in decision order, guardrails (repeat claims, currency), **backtest**; the rule editor has conditions, outcome, approval, and a live test on a case. |
| `/ops/samples`, `/ops/samples/new`, `/ops/samples/:id` | **Sample cases**: test inputs for the test lab. |
| `/ops/credentials`, `/ops/credentials/new`, `/ops/credentials/:id` | **Credentials**: API key, bearer, basic, OAuth 2.0 client credentials, custom token request. Secrets are write-only; token types have "Generate token now". |

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
│   ├── criteria.ts       Queue rules ⇄ editor form state, plain-language summaries
│   ├── credentials.ts    Credential types described once; the editor's form is built from it
│   ├── templateNames.ts  Prompt template names and fallback chains (mirrors the backend)
│   ├── compensation.ts   Compensation labels and plain-language outcome summaries
│   └── jsonpath.ts       Read JSON by dotted path (mirrors the backend)
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
│   ├── EvaluationList    Why each queue / rule did or didn't match (shared by both editors)
│   ├── CompensationCard  Case page: decision, why, approve / reject, decide again
│   ├── SimulationPanel   Compensation backtest on recent cases
│   ├── StatTile          Headline number (KPI)
│   ├── QueueHeatTable    Queue × status counts, shaded by volume
│   ├── TemplateField     Code-style input with an "Insert field…" placeholder menu
│   ├── KeyValueEditor    Header / named-secret rows
│   ├── JsonTree          API response with a "Keep" button on every value
│   ├── EnrichmentCard    Connector results on the case page + "Re-run enrichment"
│   ├── DraftPanel        AI draft details in the reply box (templates used, cost, checks, warnings)
│   ├── TemplateTestLab   Run a template on models × inputs; compare quality, consistency, cost
│   └── CostProjectionPanel  Per-reply and monthly cost per model
├── pages/                One file per route
│   └── ops/              Operations Portal pages (dashboard, queues, connectors, credentials,
│                         compensation, prompt templates, sample cases)
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
- `ReplyComposer.test.tsx`: correct message kind sent, "Send & mark solved" only when allowed, closed cases only accept notes, backend errors shown, AI draft details
- `StatusActions.test.tsx`: one button per allowed status, sends the agent and reason
- `ConditionBuilder.test.tsx`: builds all/any rules row by row, flags incomplete rows
- `QueueHeatTable.test.tsx`: every count links to the right filtered case list; shading by volume
- `TenantPicker.test.tsx`: a new tenant is selected immediately and stays selected
- `JsonTree.test.tsx`: every value (nested and list items) can be kept, with valid unique names
- `TemplateField.test.tsx`: inserting placeholders from the menu
- `pages/ops/CredentialEditorPage.test.tsx`: only the fields each credential type needs; missing fields explained
- `lib/criteria.test.ts`: rule ⇄ form round-trip, validation, summaries
- `lib/format.test.ts`, `lib/jsonpath.test.ts`: case numbers from URLs; JSON paths read like the backend
- `CompensationCard.test.tsx`: explains a pending decision, approve as the current agent, reject needs a note, final decisions can't be redone
- `lib/compensation.test.ts`: outcome summaries and money formatting
- `lib/templateNames.test.ts`: template names and fallbacks resolve exactly like the backend

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
