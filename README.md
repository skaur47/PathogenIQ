# PathogenIQ

Real-time infectious disease intelligence platform. Continuously ingests documents from global health authorities and news sources, runs a multi-agent AI pipeline to extract pathogen signals, synthesize biological profiles, mine the research literature, and generate hypothesis-driven research strategies — all without manual curation.

> All AI-generated outputs require expert review before clinical or public health application.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│  Collection  (every 4–6 h via ARQ cron)                 │
│  CDC · WHO/PAHO · ECDC · CIDRAP/ProMED · News           │
│  → relevance filter → date window → full-text extract   │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
             ┌────────────────┐
             │    Sentinel    │  extract pathogen mentions from PENDING docs
             └───────┬────────┘
                     │  auto-chains
                     ▼
             ┌────────────────┐
             │  Deduplicator  │  consolidate mention name variants
             └───────┬────────┘
                     │  auto-chains
                     ▼
             ┌────────────────┐
             │    Scholar     │  PubMed queries → biological profiles
             └───────┬────────┘
                     │  auto-chains
                     ▼
             ┌────────────────┐
             │  Deduplicator  │  merge duplicate pathogen records
             └───────┬────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
  ┌──────────────┐    ┌──────────────────┐
  │   Research   │    │    Hypothesis    │
  │ 4× PubMed   │    │ strategy + gaps  │
  │ synthesis   │    │ + experiments    │
  └──────┬───────┘    └────────┬─────────┘
         │  auto-chains        │  auto-chains
         ▼                     ▼
  ┌──────────────┐    ┌──────────────────┐
  │  Verifier   │    │    Verifier      │
  │  (research) │    │  (hypothesis)    │
  └─────────────┘    └─────────┬────────┘
                               │
                               ▼
                      ┌────────────────┐
                      │   Graph Sync   │  PostgreSQL → Neo4j
                      └────────────────┘

Full pipeline runs nightly at 02:00 UTC · Newsletter digest at 08:00 UTC
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 + uvicorn (ASGI) |
| Database | PostgreSQL 16 · SQLAlchemy 2.0 async · asyncpg |
| Migrations | Alembic (async, 8 applied revisions) |
| Knowledge Graph | Neo4j 5 (async driver) |
| Vector DB | Qdrant 1.13 |
| Cache / Queue | Redis 7 · ARQ (async task queue + cron) |
| AI Agents | LangGraph 0.2 · LangChain OpenAI · Claude claude-sonnet-4-6 |
| LLM Runtime | Ollama (local) or any OpenAI-compatible endpoint |
| Frontend | React 18 · Vite 5 · TypeScript · Tailwind CSS 3 |
| Data viz | D3 v7 (knowledge graph) · TanStack Query v5 |
| Logging | structlog (structured JSON) |

## Directory Structure

```
PathogenIQ/
├── services/
│   ├── api/
│   │   ├── app/
│   │   │   ├── agents/             # AI agent implementations
│   │   │   │   ├── sentinel.py     # pathogen mention extraction
│   │   │   │   ├── scholar.py      # PubMed biological profile synthesis
│   │   │   │   ├── deduplicator.py # mention + record deduplication
│   │   │   │   ├── research.py     # deep literature synthesis (4× PubMed queries)
│   │   │   │   ├── hypothesis.py   # research gap + strategy generation
│   │   │   │   ├── verifier.py     # output quality + coherence checks
│   │   │   │   ├── llm.py          # LLM client (Ollama / OpenAI-compatible)
│   │   │   │   ├── prompts.py      # all agent prompts
│   │   │   │   ├── filters.py      # shared LLM output filters
│   │   │   │   └── validators.py   # structured output validators
│   │   │   ├── api/v1/
│   │   │   │   ├── agents.py       # trigger + query endpoints for all agents
│   │   │   │   ├── documents.py    # ingested document listing
│   │   │   │   ├── ingestion.py    # job status endpoint
│   │   │   │   ├── newsletter.py   # subscribe / unsubscribe
│   │   │   │   └── health.py
│   │   │   ├── collectors/         # data source collectors
│   │   │   │   ├── cdc.py          # CDC MMWR RSS
│   │   │   │   ├── who.py          # PAHO (WHO Americas) RSS
│   │   │   │   ├── ecdc.py         # ECDC Communicable Disease Threats RSS
│   │   │   │   ├── promed.py       # CIDRAP infectious disease news RSS
│   │   │   │   ├── news.py         # STAT · BBC · NPR · Outbreak News · ScienceDaily
│   │   │   │   ├── pubmed.py       # NCBI E-utilities (used by Scholar + Research)
│   │   │   │   ├── filter.py       # two-gate relevance + 14-day date filter
│   │   │   │   └── fetch.py        # full-text extraction via trafilatura
│   │   │   ├── db/
│   │   │   │   ├── models/         # SQLAlchemy ORM models
│   │   │   │   │   ├── document.py
│   │   │   │   │   ├── pathogen.py
│   │   │   │   │   ├── pathogen_mention.py
│   │   │   │   │   ├── research.py
│   │   │   │   │   ├── hypothesis.py
│   │   │   │   │   ├── evidence.py
│   │   │   │   │   ├── outbreak.py
│   │   │   │   │   └── newsletter.py
│   │   │   │   └── migrations/versions/  # 001–008 Alembic revisions
│   │   │   ├── graph/
│   │   │   │   ├── neo4j_client.py # async Neo4j driver wrapper
│   │   │   │   └── sync.py         # GraphSyncAgent (PostgreSQL → Neo4j)
│   │   │   ├── repositories/       # DB access layer (one per model)
│   │   │   ├── schemas/            # Pydantic I/O schemas
│   │   │   ├── services/
│   │   │   │   ├── ingestion.py    # document dedup + persistence
│   │   │   │   └── newsletter.py   # HTML + plain email builder + SMTP delivery
│   │   │   ├── workers/
│   │   │   │   ├── tasks.py        # all ARQ task functions
│   │   │   │   └── settings.py     # WorkerSettings + cron schedule
│   │   │   ├── config.py           # pydantic-settings (reads .env)
│   │   │   └── main.py             # FastAPI app + lifespan
│   │   └── tests/
│   └── frontend/
│       ├── public/logos/           # CDC, WHO, ECDC, ProMED, PubMed, bioRxiv favicons
│       └── src/
│           ├── api/client.ts       # typed fetch wrapper for all API calls
│           ├── components/
│           │   ├── PathogenCard.tsx
│           │   ├── PathogenModal.tsx   # Research · Hypothesis · Sources tabs
│           │   ├── KnowledgeGraph.tsx  # D3 force-directed graph
│           │   ├── ResearchSection.tsx
│           │   ├── HypothesisSection.tsx
│           │   ├── SourcesSection.tsx
│           │   └── Nav.tsx
│           ├── pages/
│           │   ├── HomePage.tsx        # pathogen cards + stats + entrance animation
│           │   ├── AboutPage.tsx       # pipeline schematic + data sources
│           │   ├── ContactPage.tsx     # newsletter subscribe / unsubscribe
│           │   ├── CurrentNewsPage.tsx
│           │   ├── TrendsPage.tsx
│           │   └── GraphPage.tsx       # interactive Neo4j graph
│           └── types/index.ts
├── shared/pathogeniq_shared/schemas/  # shared Pydantic schemas
├── scripts/setup.sh
├── docker-compose.yml
└── .env.example
```

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum

# 2. Start the full stack (API, worker, Postgres, Neo4j, Qdrant, Redis, Ollama)
docker compose up

# 3. Apply migrations
docker compose exec api alembic upgrade head

# 4. API docs
open http://localhost:8000/docs

# 5. Frontend dev server (hot-reload, proxies /api → :8000)
cd services/frontend && npm install && npm run dev
open http://localhost:3000

# 6. Run tests
cd services/api && pytest -v
```

## Agents

All agents run as ARQ background tasks and can be triggered manually via HTTP or automatically via the nightly pipeline cron.

| Agent | Task | Trigger |
|---|---|---|
| **Sentinel** | Processes `PENDING` documents, extracts every pathogen/strain/virus/bacterium via LLM, normalises names to canonical form, writes frequency counts to `pathogen_mentions` | `POST /agents/trigger/sentinel` |
| **Scholar** | For each pathogen found by Sentinel, queries PubMed for recent peer-reviewed literature and synthesizes a structured biological profile (transmission routes, genome type, reservoir hosts, pandemic potential score, WHO priority) into `pathogens` | `POST /agents/trigger/scholar` |
| **Deduplicator** | Two passes: (1) consolidates mention name variants (`"COVID" → "SARS-CoV-2"`), (2) merges duplicate pathogen records in `pathogens` | `POST /agents/trigger/dedup` |
| **Research** | Runs four targeted PubMed queries per pathogen (infection mechanism, wet-lab methods, clinical trials, vaccines/therapies), summarises each article with the LLM, synthesises a four-section landscape. Stored in `research_articles` + `pathogen_research_summaries` with source URLs | `POST /agents/trigger/research` |
| **Hypothesis** | Reads biological profile + research landscape + outbreak signal. Synthesises: critical research gap, therapeutic/vaccine strategy with rationale, numbered wet-lab experiments, clinical/epidemiological approaches, and a strategic recommendation. Stored in `pathogen_hypotheses` | `POST /agents/trigger/hypothesis` |
| **Verifier** | Quality-gates Research and Hypothesis outputs — checks each field for coherence, no garbage/error strings, biological relevance to the named pathogen. Corrections written back to DB immediately | `POST /agents/trigger/verify-research` · `verify-hypothesis` |
| **Graph Sync** | Syncs all pathogen profiles from PostgreSQL into Neo4j. Builds `(:Pathogen)-[:IN_CATEGORY\|:SPREADS_VIA\|:HOSTED_BY]->()` nodes and edges using fully idempotent MERGE writes | `POST /agents/trigger/graph-sync` |

### Automatic chaining

```
Sentinel → Scholar → Dedup → Graph Sync   (automatic after each step)
Research → Verifier                        (automatic after Research)
Hypothesis → Verifier                      (automatic after Hypothesis)
```

The full pipeline task (`task_run_full_pipeline`) runs all steps sequentially every night at **02:00 UTC**.

## Data Ingestion

Five RSS/API sources feed documents into the pipeline throughout the day.

| Source | Feed | Cron (UTC) |
|---|---|---|
| CDC MMWR | `cdc.gov/mmwr/rss/mmwr.xml` | Every 4 h at :05 |
| WHO/PAHO + ECDC | PAHO Americas + ECDC CDT feeds | Every 4 h at :10 |
| CIDRAP / ProMED | `cidrap.umn.edu/rss.xml` | Every 6 h at :02 |
| News | STAT · BBC Health · NPR Health · Outbreak News Today · ScienceDaily | Every 4 h at :15 |

**Filtering pipeline** applied to every incoming document:

1. **Gate 1 — Exclusion**: drops vaccine-policy, mental health, lifestyle, review/opinion, and drug-toxicology content based on title keywords.
2. **Gate 2 — Outbreak signal**: requires at least one active-outbreak keyword or high-consequence pathogen name in title + abstract.
3. **Date window**: only articles published within the last **14 days** are ingested.
4. **Full-text extraction**: surviving documents have their body text fetched and extracted via [trafilatura](https://trafilatura.readthedocs.io/), replacing the RSS summary.

Up to **150 documents per source** per collection run. PubMed is driven on-demand by Scholar and Research (NCBI ESearch queries keyed to specific pathogen names).

## API Reference

```
# Agent triggers — all return 202 + job_id
POST /api/v1/agents/trigger/sentinel
POST /api/v1/agents/trigger/scholar
POST /api/v1/agents/trigger/dedup
POST /api/v1/agents/trigger/research
POST /api/v1/agents/trigger/hypothesis
POST /api/v1/agents/trigger/verify-research
POST /api/v1/agents/trigger/verify-hypothesis
POST /api/v1/agents/trigger/graph-sync

# Query agent outputs
GET  /api/v1/agents/pathogens               # biological profiles (+ pagination)
GET  /api/v1/agents/mentions                # pathogen frequency table
GET  /api/v1/agents/research/{name}         # literature landscape + source URLs
GET  /api/v1/agents/hypothesis/{name}       # research strategy
GET  /api/v1/agents/sources/{name}          # source documents for a pathogen
GET  /api/v1/agents/graph                   # Neo4j graph data for visualisation
GET  /api/v1/agents/pipeline-status         # last-run timestamps and doc counts
GET  /api/v1/agents/pathogen-trends         # mention frequency over time

# Documents
GET  /api/v1/documents                      # ingested document list (source, limit, offset)

# Job status
GET  /api/v1/ingestion/jobs/{job_id}        # ARQ task result (kept 7 days)

# Newsletter
POST /api/v1/newsletter/subscribe           # { name, email } → 201
POST /api/v1/newsletter/unsubscribe         # { token: UUID } → 200 / 404
```

## Newsletter

Subscribers receive a daily HTML digest of all active pathogen profiles (transmission routes, reservoir hosts, WHO priority, description). The digest is sent at **08:00 UTC** via `task_send_newsletter`.

**Subscribe**: visit `/contact` in the frontend or `POST /api/v1/newsletter/subscribe`.

**Unsubscribe**: each email includes a one-click link → `/contact?unsubscribe=<uuid>`.

To enable email delivery, set in `.env`:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char Gmail app password>   # requires 2FA + App Passwords
SMTP_FROM=PathogenIQ <noreply@yourdomain.com>
FRONTEND_BASE_URL=https://yourdomain.com
```

When `SMTP_HOST` is empty, subscriptions are saved to the DB but no email is sent.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL async DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | — | Redis DSN (`redis://redis:6379`) |
| `NEO4J_URI` | — | Bolt URI (`bolt://neo4j:7687`) |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | — | Neo4j password |
| `QDRANT_URL` | — | Qdrant HTTP URL |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (used by Scholar, Research, Hypothesis, Verifier) |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | `llama3.2` | Model name at that endpoint |
| `LLM_API_KEY` | `ollama` | API key (`ollama` for local, real key for cloud) |
| `SMTP_HOST` | `` | SMTP server hostname (empty = email disabled) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | `` | SMTP username |
| `SMTP_PASSWORD` | `` | SMTP password |
| `SMTP_FROM` | `PathogenIQ <noreply@pathogeniq.io>` | From address |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Used in unsubscribe links |
| `ENVIRONMENT` | `development` | `development` / `production` |

## Development Status

- **Phase 1** ✓ — Backend foundation: FastAPI, PostgreSQL, health checks, models, repositories
- **Phase 2** ✓ — Data ingestion: CDC/WHO/ECDC/CIDRAP/News collectors, relevance + date filters, full-text extraction, ARQ cron scheduler
- **Phase 3** ✓ — AI pipeline: Sentinel → Scholar → Deduplicator → Research → Hypothesis → Verifier (LangGraph + Claude claude-sonnet-4-6)
- **Phase 4** ✓ — Knowledge graph: Neo4j sync, graph query API, D3 visualisation
- **Phase 5** ✓ — Frontend: React 18 + Vite dashboard, pathogen cards, research/hypothesis modal, interactive graph, newsletter, trends
- **Phase 6** — Production: CI/CD, monitoring, Kubernetes deployment
