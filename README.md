# Local CRM

A customer care **resolution engine**: it takes in customer cases, enriches them with data from the business's own systems, decides compensation using rules the business configures, drafts replies with AI, and routes anything risky to a human.

> Status: **early.** Working: case intake (API + test webform), case lifecycle, agent replies and notes, audit trail, queue routing, Operations Portal (queues, dashboard), and **enrichment**: connectors with shared credentials (incl. OAuth / generated tokens), a background worker, and routing on enriched data. Next: compensation matrix, AI drafting.

## Repository layout

```
.
├── backend/              Python / FastAPI API (see backend/README.md)
├── frontend/             React / TypeScript UI (see frontend/README.md)
├── docs/
│   ├── README.md         Architecture notes and product docs — start here
│   ├── 04-product-ideas.md
│   ├── 05-data-model.md
│   └── dev/              Developer guides
│       ├── local-setup.md
│       ├── codebase-guide.md
│       └── database-guide.md
└── docker-compose.yml    Local stack (Postgres + API + UI)
```

## Quick start

**With Docker** (recommended; install [Docker Desktop](https://www.docker.com/products/docker-desktop/) first):

```bash
docker compose up --build
```

Then open **http://localhost:5173** for the app (agent console + test webform), or **http://localhost:8000/docs** for the interactive API docs.

**Without Docker**, and other options: see [docs/dev/local-setup.md](docs/dev/local-setup.md).

## Developer guides

| Guide | Read it when… |
|---|---|
| [Local setup](docs/dev/local-setup.md) | Getting the project running, running tests |
| [Codebase guide](docs/dev/codebase-guide.md) | Understanding how the code is organized and adding a feature |
| [Database guide](docs/dev/database-guide.md) | Working with Postgres, models and migrations (written for someone coming from a document database) |
