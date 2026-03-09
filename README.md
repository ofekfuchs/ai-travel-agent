# AI Travel Agent

Autonomous full-package travel planning agent built for the AI Agents course (Technion).
Given a free-form travel request, the agent reasons at every decision point, searches
real flights/hotels/weather/POIs, and returns complete priced trip packages.

**Team:** Ofek Fuchs & Omri Lazover | **Group:** 3_11

---

## Quick Start

### 1. Prerequisites

- Python 3.11+ (tested with 3.14)
- API keys (see `.env` section below)

### 2. Install dependencies

```bash
cd ai-travel-agent
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root with:

```env
# LLM (LLMod.ai)
LLM_API_KEY=your_llmod_api_key
LLM_BASE_URL=https://api.llmod.ai/v1
LLM_MODEL=your_model_name
EMBEDDING_MODEL=your_embedding_model

# Pinecone (RAG - Wikivoyage knowledge)
PINECONE_API_KEY=your_pinecone_key
PINECONE_ENVIRONMENT=your_pinecone_env
PINECONE_INDEX_NAME=wikivoyage-index

# Supabase (caching + persistence)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key

# External APIs
RAPIDAPI_KEY=your_rapidapi_key
OPENTRIPMAP_API_KEY=your_opentripmap_key
```

### 4. Run the server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 5. Use the agent

- **UI:** Open http://127.0.0.1:8001 in your browser
- **API:** `POST http://127.0.0.1:8001/api/execute` with `{"prompt": "your travel request"}`

---

## Architecture

### Supervisor-Driven Agentic Loop (ReAct Pattern)

The system is a **true agent**, not a static workflow. The Supervisor is called at
every decision point — it observes intermediate results and adapts:

```
User Request
    │
    ▼
┌─────────────┐
│  Supervisor  │◄──────────────────────────────┐
│  (decision)  │                               │
└──────┬──────┘                               │
       │                                      │
  ┌────┴────┬──────────┬───────────┐          │
  ▼         ▼          ▼           ▼          │
clarify   plan      continue    synthesize    │
  │         │          │           │          │
  │    ┌────▼────┐  ┌──▼───┐  ┌───▼────┐     │
  │    │ Planner │  │Exec. │  │Synth.  │     │
  │    │+RAG     │  │Phase │  │+Verify │     │
  │    └────┬────┘  └──┬───┘  └───┬────┘     │
  │         │          │          │           │
  │    ┌────▼────┐     │     ┌────▼────┐      │
  │    │Executor │     │     │APPROVE? │──────┘
  │    │Phase 1  │     │     │ or loop │
  │    └────┬────┘     │     └─────────┘
  │         │          │
  ▼         └──────────┘
Return         (loop back to Supervisor)
```

### Components

| Component | Role | LLM Calls |
|-----------|------|-----------|
| **Supervisor** | Brain — decides next action at every step | 1 per round (3+ rounds typical) |
| **Planner** | Extracts constraints + generates task plan + RAG | 1 call |
| **Executor** | Runs tools (flights, hotels, weather, POIs) | 0 (pure API calls) |
| **Synthesizer** | Builds tiered trip packages from data | 1 call |
| **Verifier** | Quality audit (rule-based + LLM) | 1 call |

### External Services

| Service | Purpose | Cost |
|---------|---------|------|
| LLMod.ai | LLM reasoning (all agents) | ~$0.01-0.05/call |
| Pinecone | RAG vector DB (Wikivoyage) | Free tier |
| Supabase | Caching, trip storage, session persistence | Free tier |
| RapidAPI (Booking.com) | Flights + Hotels search | Freemium |
| Open-Meteo | Weather forecasts | Free |
| OpenTripMap | Points of interest | Free |

### LLM Budget

Each request has a hard cap of **8 LLM calls**. Typical successful run uses 6:

| Call | Agent | Purpose |
|------|-------|---------|
| 1 | Supervisor | Initial routing decision |
| 2 | Planner | Extract constraints + generate tasks |
| 3 | Supervisor | Observe Phase 1 results, decide continue |
| 4 | Supervisor | Observe Phase 2 results, decide synthesize |
| 5 | Synthesizer | Build trip packages |
| 6 | Verifier | Quality audit |
| 7-8 | (spare) | Available for replanning if rejected |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Frontend UI |
| GET | `/health` | Health check |
| GET | `/api/team_info` | Team information |
| GET | `/api/agent_info` | Agent description and examples |
| GET | `/api/model_architecture` | Architecture diagram (PNG) |
| POST | `/api/execute` | Main endpoint — plan a trip |

### POST /api/execute

**Request:**
```json
{"prompt": "Beach vacation in June from New York"}
```

**Response (success):**
```json
{
  "status": "ok",
  "response": "[{\"label\": \"Budget Pick\", \"destination\": \"Miami\", ...}]",
  "steps": [{"module": "Supervisor", "prompt": {...}, "response": {...}}, ...]
}
```

---

## Project Structure

```
ai-travel-agent/
├── app/
│   ├── main.py                 # FastAPI app + Supervisor-driven loop
│   ├── config.py               # Environment variables
│   ├── agents/
│   │   ├── supervisor.py       # Decision-making brain (multi-call)
│   │   ├── planner.py          # Constraint extraction + task planning + RAG
│   │   ├── executor.py         # Pure tool runner (no LLM)
│   │   ├── synthesizer.py      # Trip package builder
│   │   └── verifier.py         # Quality auditor (hybrid)
│   ├── tools/
│   │   ├── flights_tool.py     # Booking.com Flights API
│   │   ├── hotels_tool.py      # Booking.com Hotels API
│   │   ├── weather_tool.py     # Open-Meteo (forecast + climate normals)
│   │   ├── poi_tool.py         # OpenTripMap POIs
│   │   ├── rag_tool.py         # Pinecone/Wikivoyage search
│   │   └── geocode.py          # City name → lat/lon
│   ├── llm/
│   │   └── client.py           # LLM wrapper with call cap enforcement
│   ├── rag/
│   │   ├── retriever.py        # Pinecone query logic
│   │   └── ingest.py           # Wikivoyage data ingestion
│   ├── models/
│   │   ├── shared_state.py     # Central state dataclass
│   │   └── schemas.py          # Pydantic API schemas
│   └── utils/
│       ├── cache.py            # Two-level cache (memory + Supabase)
│       ├── trip_store.py       # Persist trips/sessions/logs to Supabase
│       └── step_logger.py      # Tool invocation logger
├── frontend/
│   ├── index.html              # UI
│   ├── script.js               # Client-side logic
│   └── style.css               # Styles
├── scripts/
│   ├── ingest_wikivoyage.py    # Seed Pinecone with Wikivoyage data
│   └── test_tools_dry.py       # Dry-run tool tests
├── .env                        # API keys (not committed)
├── requirements.txt            # Python dependencies
├── architecture.png            # System diagram
├── TESTING.md                  # Test checklist
└── README.md                   # This file
```

---

## Supabase Setup

Create these tables in your Supabase project (SQL Editor):

```sql
-- Tool result caching
CREATE TABLE IF NOT EXISTS cache (
  id BIGSERIAL PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  value JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Completed trip storage
CREATE TABLE IF NOT EXISTS trips (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  session_id TEXT,
  prompt TEXT,
  constraints JSONB,
  packages JSONB,
  llm_calls_used INTEGER,
  status TEXT DEFAULT 'approved'
);

-- Session persistence
CREATE TABLE IF NOT EXISTS sessions (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  session_id TEXT,
  prompt TEXT,
  state_snapshot JSONB
);

-- Execution audit trail
CREATE TABLE IF NOT EXISTS execution_logs (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  session_id TEXT,
  round_num INTEGER,
  action TEXT,
  reason TEXT,
  data_snapshot JSONB
);
```

---

## What Makes This an Agent (Not Just a Workflow)

1. **Multi-round Supervisor**: Called 3+ times per request, observes and adapts
2. **Phased execution**: Searches destinations one at a time, reasons about results
3. **Adaptive decisions**: Can skip expensive destinations, pivot to cheaper ones
4. **Scope guard**: Refuses non-travel requests politely
5. **RAG grounding**: Uses Wikivoyage knowledge to inform destination choices
6. **Budget-aware reasoning**: Compares prices to budget at every decision point
7. **Self-healing**: On Verifier rejection, loops back for delta replanning
