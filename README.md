# PathogenIQ

Real-time infectious disease intelligence platform. Continuously ingests documents from global health authorities and news sources, runs a multi-agent AI pipeline to extract pathogen signals, synthesize biological profiles, mine the research literature, and generate hypothesis-driven research strategies — all without manual curation.

> All AI-generated outputs require expert review before clinical or public health application.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│  Collection  (every 4–6 h via ARQ cron)                 │
│  CDC · WHO/PAHO · ECDC · CIDRAP/ProMED · News           │
│  → relevance filter → 14-day date window → full-text    │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
             ┌────────────────┐
             │    Sentinel    │  extract pathogen mentions from PENDING docs
             └───────┬────────┘
                     │  auto-chains
                     ▼
             ┌────────────────┐
             │    Scholar     │  PubMed queries → biological profiles
             └───────┬────────┘
                     │  auto-chains
                     ▼
             ┌────────────────┐
             │  Deduplicator  │  consolidate name variants + merge duplicate records
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
  │   Verifier   │    │    Verifier      │
  │  (research)  │    │  (hypothesis)    │
  └─────────────┘    └────────┬─────────┘
                               │
                               ▼
                      ┌────────────────┐
                      │   Graph Sync   │  PostgreSQL → Neo4j
                      └────────────────┘

All steps triggered manually via API — automatic cron scheduling is disabled
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 + uvicorn (ASGI) |
| Database | PostgreSQL 16 · SQLAlchemy 2.0 async · asyncpg |
| Migrations | Alembic |
| Knowledge Graph | Neo4j 5 (async driver) |
| Vector DB | Qdrant |
| Cache / Queue | Redis · ARQ (async task queue + cron) |
| AI Agents | LangGraph · LangChain |
| LLM | Groq (OpenAI-compatible endpoint, `llama-3.1-8b-instant`) |
| Frontend | React 18 · Vite 5 · TypeScript · Tailwind CSS 3 |
| Data viz | D3 v7 (knowledge graph) · TanStack Query v5 |
| Logging | structlog (structured JSON) |

## External Services

| Service | Used for |
|---|---|
| **PostgreSQL** | Primary data store — documents, pathogens, research, hypotheses |
| **Redis Cloud** | ARQ task queue + cron trigger store + job result cache |
| **Neo4j Aura** | Knowledge graph — pathogen relationship nodes and edges |
| **Qdrant Cloud** | Vector embeddings (future semantic search) |
| **Groq API** | LLM inference for all agents (free tier: `llama-3.1-8b-instant`) |
| **PubMed / NCBI E-utilities** | Literature queries by Scholar and Research agents |
| **Vercel** | Frontend static hosting |
| **SMTP** | Newsletter delivery (optional — any SMTP provider or Gmail app password) |

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
│   │   │   │   ├── llm.py          # LLM client (OpenAI-compatible)
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
│   │   │   │   └── migrations/versions/  # Alembic revisions
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
│       ├── public/logos/           # CDC, WHO, ECDC, ProMED, PubMed favicons
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

## Quick Start (local)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set Groq API key and connection strings for your external services

# 2. Start the full stack (API, worker, Postgres, Neo4j, Qdrant, Redis)
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

## Deployment

The API and background worker are deployed as two separate services on **Render**. The worker runs 24/7 and handles all ARQ cron jobs. The frontend is deployed as a static site on **Vercel**.

**Render setup:**
- `api` web service — uvicorn, port 8000, `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- `worker` background worker — `arq app.workers.settings.WorkerSettings`
- Set all connection strings and API keys as environment variables in the Render dashboard

**Vercel setup:**
- Root: `services/frontend`, build command: `npm run build`, output: `dist`
- Add `VITE_API_BASE_URL` pointing to your Render API URL

## Agents

All agents run as ARQ background tasks and can be triggered manually via HTTP or automatically via the nightly pipeline.

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

The full pipeline task (`task_run_full_pipeline`) runs all steps sequentially and is triggered manually via `POST /agents/trigger/full-pipeline`. Automatic cron scheduling is defined in `workers/settings.py` but currently disabled.

## Data Ingestion

Five RSS/API sources feed documents into the pipeline throughout the day.

| Source | Feed | Schedule |
|---|---|---|
| CDC MMWR | `cdc.gov/mmwr/rss/mmwr.xml` | Manual (`POST /agents/trigger/collect-cdc`) |
| WHO/PAHO + ECDC | PAHO Americas + ECDC CDT feeds | Manual (`POST /agents/trigger/collect-who`) |
| CIDRAP / ProMED | `cidrap.umn.edu/rss.xml` | Manual (`POST /agents/trigger/collect-promed`) |
| News | STAT · BBC Health · NPR Health · Outbreak News Today · ScienceDaily | Manual (`POST /agents/trigger/collect-news`) |

**Filtering pipeline** applied to every incoming document:

1. **Gate 1 — Exclusion**: drops vaccine-policy, mental health, lifestyle, review/opinion, and drug-toxicology content based on title keywords.
2. **Gate 2 — Outbreak signal**: requires at least one active-outbreak keyword or high-consequence pathogen name in title + abstract.
3. **Date window**: only articles published within the last **14 days** are ingested.
4. **Full-text extraction**: surviving documents have their body text fetched and extracted via [trafilatura](https://trafilatura.readthedocs.io/), replacing the RSS summary.

Up to **150 documents per source** per collection run. PubMed is driven on-demand by Scholar and Research agents using NCBI ESearch queries keyed to specific pathogen names.

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
GET  /api/v1/ingestion/jobs/{job_id}        # ARQ task result (kept 1 hour)

# Newsletter
POST /api/v1/newsletter/subscribe           # { name, email } → 201
POST /api/v1/newsletter/unsubscribe         # { token: UUID } → 200 / 404
```

## Newsletter

Subscribers receive a daily HTML digest of all active pathogen profiles (transmission routes, reservoir hosts, WHO priority, description). The digest is sent at **08:00 UTC** as step 8 of the full pipeline task.

**Subscribe**: visit `/contact` in the frontend or `POST /api/v1/newsletter/subscribe`.

**Unsubscribe**: each email includes a one-click link → `/contact?unsubscribe=<uuid>`.

Email delivery requires an SMTP provider configured via environment variables. When `SMTP_HOST` is not set, subscriptions are saved to the DB but no email is sent.
