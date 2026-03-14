# AI Travel Agent

Autonomous full-package travel planning agent built for the **AI Agents course (Technion)**.
Given a free-form travel request, the agent reasons at every decision point, searches
real flights/hotels/weather/POIs, and returns complete priced trip packages.

**Team:** Ofek Fuchs & Omri Lazover | **Group:** 3_11

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Key Features](#key-features)
4. [API Endpoints](#api-endpoints)
5. [Project Structure](#project-structure)
6. [Testing](#testing)
7. [Supabase Setup](#supabase-setup)
8. [Configuration](#configuration)
9. [What Makes This an Agent](#what-makes-this-an-agent-not-just-a-workflow)

---

## Quick Start

### 1. Prerequisites

- Python 3.11+ (tested with 3.14)
- API keys (see [Configuration](#configuration) section below)

### 2. Install dependencies

```bash
cd ai-travel-agent
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root (see [Configuration](#configuration) for details).

### 4. Seed RAG knowledge base (optional but recommended)

```bash
python scripts/seed_test_data.py
```

This populates Pinecone with Wikivoyage destination knowledge (~350 cities).

### 5. Run the server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 6. Use the agent

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

### Component Overview

| Component | Role | LLM Calls |
|-----------|------|-----------|
| **Supervisor** | Brain — decides next action at every step | 1 per round (3+ rounds typical) |
| **Planner** | Extracts constraints + generates task plan + RAG | 1 call |
| **Executor** | Runs tools in parallel (flights, hotels, weather, POIs) | 0 (pure API calls) |
| **Synthesizer** | Builds tiered trip packages from data | 1 call |
| **Verifier** | Quality audit (deterministic rules + LLM) | 1 call |

### External Services

| Service | Purpose | Cost |
|---------|---------|------|
| LLMod.ai / Azure OpenAI | LLM reasoning (all agents) | ~$0.01-0.05/call |
| Pinecone | RAG vector DB (Wikivoyage) | Free tier |
| Supabase | Caching, trip storage, session persistence | Free tier |
| RapidAPI (Booking.com) | Flights + Hotels search | Freemium |
| Open-Meteo | Weather forecasts | Free |
| OpenTripMap | Points of interest | Free |

### LLM Budget

Each request has a hard cap of **12 LLM calls** (configurable). Typical successful run uses 5-7:

| Call | Agent | Purpose |
|------|-------|---------|
| 1 | Supervisor | Initial routing decision |
| 2 | Planner | Extract constraints + generate tasks |
| 3 | Supervisor | Observe Phase 1 results, decide continue |
| 4 | Supervisor | Observe Phase 2 results, decide synthesize |
| 5 | Synthesizer | Build trip packages |
| 6 | Verifier | Quality audit |
| 7-12 | (spare) | Available for replanning if rejected |

---

## Key Features

### Intelligent Decision Making
- **Multi-round Supervisor (ReAct)**: Called 3+ times per request with Thought → Action → Observation cycles
- **Phased execution**: Searches destinations one at a time, observing results between phases
- **Adaptive decisions**: Can skip expensive destinations, pivot to cheaper ones based on observations
- **Scope guard**: Politely refuses non-travel requests

### Data Validation & Quality
- **Flight sanity filtering**: Rejects invalid flight data (missing timestamps, impossible durations, nonstop > 20h)
- **Deterministic verifier rules**: Budget violations, missing fields, fabricated transport force rejection
- **Pre-synthesis consistency checks**: Validates destination overlap between flights and hotels
- **Early budget feasibility (Gate B)**: Stops immediately when budget is provably infeasible

### RAG Knowledge
- **Wikivoyage integration**: ~350 cities seeded with travel knowledge
- **Context-aware planning**: Uses destination knowledge to inform itineraries

### Session Continuity
- **Multi-turn conversations**: Follow-up messages inherit context
- **Constraint updates**: Users can modify budget, dates, preferences mid-conversation

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
{
  "prompt": "Beach vacation in June from New York",
  "session_id": "optional-for-follow-ups"
}
```

**Response (success):**
```json
{
  "status": "ok",
  "response": "{\"trip_packages\": [...]}",
  "steps": [...],
  "session_id": "uuid",
  "llm_calls_used": 6,
  "elapsed_seconds": 134.5
}
```

**Response types:**
- `status: "ok"` + `trip_packages` — successful planning
- `status: "ok"` + `budget_infeasible` — budget too low (with alternatives)
- `status: "ok"` + `clarification` — needs more information
- `status: "error"` — system error

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
│   │   ├── flights_tool.py     # Booking.com Flights API + sanity filter
│   │   ├── hotels_tool.py      # Booking.com Hotels API
│   │   ├── weather_tool.py     # Open-Meteo (forecast + climate normals)
│   │   ├── poi_tool.py         # OpenTripMap POIs
│   │   ├── rag_tool.py         # Pinecone/Wikivoyage search
│   │   └── geocode.py          # City name → lat/lon
│   ├── llm/
│   │   └── client.py           # LLM wrapper with call cap enforcement
│   ├── rag/
│   │   └── retriever.py        # Pinecone query logic
│   ├── models/
│   │   ├── shared_state.py     # Central state dataclass
│   │   └── schemas.py          # Pydantic API schemas
│   └── utils/
│       ├── cache.py            # Two-level cache (memory + Supabase)
│       ├── trip_store.py       # Persist trips/sessions/logs to Supabase
│       └── step_logger.py      # Tool invocation logger
├── frontend/
│   ├── index.html              # UI with live progress indicator
│   ├── script.js               # Client-side logic
│   └── style.css               # Modern responsive styles
├── scripts/
│   ├── seed_test_data.py       # Seed Pinecone with Wikivoyage data
│   ├── test_e2e_smoke.py       # E2E smoke tests (10 scenarios)
│   ├── run_verifier_tests.py   # Verifier stress tests
│   ├── check_endpoints.py      # API endpoint validation
│   └── run_tests.py            # Test runner utility
├── tests/
│   └── test_deterministic.py   # 89 unit tests (zero-LLM)
├── .env                        # API keys (not committed)
├── requirements.txt            # Python dependencies
├── architecture.png            # System diagram
├── ARCHITECTURE.md             # Detailed architecture documentation
├── TESTING.md                  # Basic test checklist
├── TESTING_EXTENDED.md         # Extended test scenarios
├── TODO.md                     # Feature tracking
└── README.md                   # This file
```

---

## Testing

### Unit Tests (89 tests, zero LLM calls)

```bash
python -m pytest tests/ -v
```

Covers:
- Feasibility checks (Gate B budget guard)
- Rejection classification
- Destination grouping and task splitting
- Cache key generation
- Flight sanity filtering
- Verifier hard failure logic
- Pre-synthesis consistency checks
- Session continuity
- Price cross-checking

### E2E Smoke Tests

```bash
# Start the server first
uvicorn app.main:app --host 127.0.0.1 --port 8001

# Run all tests
python scripts/test_e2e_smoke.py --base-url http://127.0.0.1:8001

# Run specific test
python scripts/test_e2e_smoke.py --test 1
```

**Test scenarios:**
1. Beach vacation from NYC
2. Europe trip with flexible dates
3. Specific destination (Rome)
4. Budget infeasibility detection
5. RAG-influenced destinations
6. Multi-traveler pricing
7. Session continuity
8. Off-topic request handling
9. Family vacation (complex)
10. Budget-tight scenario

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

## Configuration

Create a `.env` file in the project root:

```env
# LLM Provider (Azure OpenAI via LLMod.ai or direct)
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.llmod.ai/v1
LLM_MODEL=gpt-4o
EMBEDDING_MODEL=text-embedding-3-small

# Pinecone (RAG - Wikivoyage knowledge)
PINECONE_API_KEY=your_pinecone_key
PINECONE_ENVIRONMENT=your_pinecone_env
PINECONE_INDEX_NAME=wikivoyage-index

# Supabase (caching + persistence)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key

# External APIs
RAPIDAPI_KEY=your_rapidapi_key           # For Booking.com flights/hotels
OPENTRIPMAP_API_KEY=your_opentripmap_key # For POIs
```

### Optional Configuration (in `app/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CALL_CAP` | 12 | Max LLM calls per request |
| `MAX_SUPERVISOR_ROUNDS` | 8 | Max supervisor iterations |
| `DAILY_EXPENSES_ESTIMATE` | 50 | Default daily expense ($) |
| `BUDGET_TOLERANCE` | 1.05 | Budget check tolerance (5%) |

---

## What Makes This an Agent (Not Just a Workflow)

1. **Multi-round Supervisor (ReAct)**: Called 3+ times per request — Thought → Action → Observation cycles
2. **Phased execution**: Searches destinations one at a time, observes results between phases
3. **Adaptive decisions**: Can skip expensive destinations, pivot to cheaper ones based on observations
4. **Per-destination reasoning**: Supervisor compares prices across destinations to make informed decisions
5. **Scope guard**: Refuses non-travel requests politely
6. **RAG grounding**: Uses Wikivoyage knowledge to inform destination choices
7. **Budget-aware reasoning**: Compares prices to budget at every decision point
8. **Self-healing**: On Verifier rejection (Reflection), loops back for delta replanning
9. **Parallel tool execution**: Flight/hotel/weather/POI searches run concurrently within each phase
10. **Session continuity**: Multi-turn conversations with context inheritance

---

## Example Prompts

```
"Beach vacation in June from New York"
"4 days in Rome in September, budget $1500 from NYC"
"Family trip to Barcelona, 5 adults, August 10-17 2026, budget $7000 from TLV"
"Europe in May, best value for money, 1 week"
"Trip to Tokyo for 2 weeks from New York, budget $3000"
```

---

## License

MIT License - See LICENSE file for details.
