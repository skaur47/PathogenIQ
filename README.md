# PathogenIQ

Real-time infectious disease intelligence and therapeutic discovery platform.

> All AI-generated outputs require expert review before clinical or public health application.

## Architecture

```
PathogenIQ/
├── services/
│   └── api/                 # FastAPI backend
│       ├── app/
│       │   ├── main.py      # FastAPI app + lifespan
│       │   ├── config.py    # Pydantic settings
│       │   ├── api/v1/      # HTTP endpoints
│       │   ├── collectors/  # Data source collectors (Phase 2)
│       │   │   ├── cdc.py       # CDC MMWR RSS
│       │   │   ├── who.py       # PAHO (WHO Americas) RSS
│       │   │   ├── ecdc.py      # ECDC Communicable Disease Threats RSS
│       │   │   ├── promed.py    # CIDRAP infectious disease news RSS
│       │   │   ├── news.py      # STAT / BBC / NPR / Outbreak News / ScienceDaily
│       │   │   ├── pubmed.py    # PubMed via NCBI E-utilities (Phase 3)
│       │   │   ├── filter.py    # Two-gate outbreak relevance + 14-day date filter
│       │   │   └── fetch.py     # Full article text extraction (trafilatura)
│       │   ├── workers/     # ARQ background tasks + cron scheduler
│       │   ├── db/          # SQLAlchemy models + Alembic migrations
│       │   ├── repositories/ # Database access layer
│       │   └── core/        # Logging, utilities
│       └── tests/
├── shared/                  # Shared Pydantic schemas
├── scripts/                 # Dev helper scripts
├── docker-compose.yml       # Local dev stack
└── .env.example
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + uvicorn |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async |
| Knowledge Graph | Neo4j 5 |
| Vector DB | Qdrant |
| Cache / Queue | Redis 7 |
| Migrations | Alembic (async) |
| AI Agents | LangGraph (Phase 3) |
| Frontend | Next.js (Phase 5) |

## Quick Start

```bash
# 1. Setup (first time only)
chmod +x scripts/setup.sh && ./scripts/setup.sh

# 2. Start everything
docker compose up

# 3. Open API docs
open http://localhost:8000/docs

# 4. Run tests
cd services/api && pytest -v
```

## Agents (Phase 3)

| Agent | Role |
|---|---|
| Sentinel | Scans ingested documents, extracts pathogen mentions, builds frequency table |
| Scholar | For each pathogen found by Sentinel, queries PubMed and synthesizes biological profile |
| Mechanica | Mutation analysis, immune escape *(planned)* |
| Intervention | Therapeutic candidate identification *(planned)* |
| GraphMind | Neo4j knowledge graph construction *(planned)* |
| Verifier | Citation verification, hallucination prevention *(planned)* |
| Frontier | Research gap detection *(planned)* |
| Atlas | Executive synthesis, risk briefings *(planned)* |

### Sentinel Agent

Processes all `PENDING` documents from Phase 2 ingestion. For each article, asks Claude to extract every pathogen/strain/virus/bacteria mentioned, normalize names to canonical form (e.g. `"COVID" → "SARS-CoV-2"`), and count occurrences. Results are written to the `pathogen_mentions` table and aggregated into a frequency table:

```
SARS-CoV-2        | 17 mentions | 5 documents
Influenza A H5N1  |  9 mentions | 4 documents
Mpox virus        |  4 mentions | 2 documents
```

### Scholar Agent

For each pathogen discovered by Sentinel, Scholar queries PubMed for recent peer-reviewed literature (2023–present) and uses Claude to synthesize a structured biological profile:

| Field | Example |
|---|---|
| category | `virus` |
| transmission_routes | `["airborne", "droplet"]` |
| reservoir_hosts | `["bats", "humans"]` |
| genome_type | `ssRNA+` |
| description | 2–4 sentence clinical + epidemiological summary |
| who_priority | `true` |
| pandemic_potential_score | `0.82` (0–1 scale) |

Profiles are upserted into the `pathogens` table. Sentinel automatically chains Scholar on completion.

### Phase 3 API Endpoints

```
POST /api/v1/agents/trigger/sentinel   → 202 + job_id  (run Sentinel + auto-chains Scholar)
POST /api/v1/agents/trigger/scholar    → 202 + job_id  (run Scholar independently)
GET  /api/v1/agents/mentions           → pathogen frequency table
GET  /api/v1/agents/pathogens          → biological profiles
```

## Phase 2 — Data Ingestion

Five outbreak-focused RSS sources run on ARQ background tasks with automatic cron scheduling.

| Source | Feed | Schedule | Notes |
|--------|------|----------|-------|
| CDC MMWR | `cdc.gov/mmwr/rss/mmwr.xml` | Every 4 h | 500-item prefetch |
| WHO/PAHO | `paho.org/en/rss.xml` | Every 4 h | WHO Americas alerts |
| ECDC | `ecdc.europa.eu/…/323/feed` | Every 4 h | EU Communicable Disease Threats |
| CIDRAP (ProMED) | `cidrap.umn.edu/rss.xml` | Every 6 h | Expert-curated ID journalism |
| News | STAT / BBC / NPR / Outbreak News Today / ScienceDaily | Every 4 h | 5 feeds, concurrent fetch |

**Filtering pipeline** (applied to every incoming document):

1. **Gate 1 — Exclusion**: drops vaccine-policy, mental health, lifestyle, review/opinion, and drug-toxicology content matched against the title.
2. **Gate 2 — Outbreak signal**: requires at least one active-outbreak keyword or high-consequence pathogen name in title + abstract.
3. **Date window**: only articles published within the last **14 days** are ingested.
4. **Full-text extraction**: surviving documents have their body text fetched and extracted via [trafilatura](https://trafilatura.readthedocs.io/), replacing the RSS summary in `raw_content`.

Up to **150 documents per source** are stored per collection run.

**PubMed** is deferred to Phase 3 — the Scholar agent will drive NCBI ESearch queries dynamically based on Sentinel signals, and abstracts are most valuable once paired with the Qdrant embedding pipeline.

## Development Phases

- **Phase 1** ✓ — Backend foundation: FastAPI, PostgreSQL, health checks, models, repositories
- **Phase 2** ✓ — Data ingestion: CDC/WHO/ECDC/CIDRAP/news collectors, relevance + date filters, full-text extraction, ARQ cron scheduler
- **Phase 3** ✓ — AI layer: Sentinel (pathogen extraction) + Scholar (PubMed profile synthesis), LangGraph, Claude claude-sonnet-4-6
- **Phase 4** — Knowledge graph: Neo4j relationships, graph queries
- **Phase 5** — Frontend: Next.js dashboard, real-time alerts, graph visualization
- **Phase 6** — Production: CI/CD, monitoring, Kubernetes deployment
