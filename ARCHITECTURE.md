# AI Travel Agent - System Architecture

## Overview

This document describes the architecture of an **autonomous AI Travel Agent** that uses a **Supervisor-driven ReAct pattern** to plan complete trip packages from free-form user requests.

### Real architecture (as implemented)

The diagrams and sections below match the codebase:

- **RAG (Pinecone Wikivoyage):** The **Planner** queries RAG (e.g. prefetch via `search_destinations`) and stores results in **SharedState** as `destination_chunks`. The **Executor** can also run `rag_search` tasks that query RAG. The **Trip Synthesizer** does not call Pinecone; it uses **RAG chunks from SharedState** (`state.destination_chunks`) to ground itineraries in Wikivoyage knowledge.
- **Supabase:** Primary persistence layer. Used for **cache** (tool results), **trips**, **sessions**, and **execution_logs**. The PNG diagram and Mermaid both show Supabase in the data layer; the README Mermaid is simplified but references it in the text.
- **Flow:** Supervisor → Planner (plan/replan) → Executor (tasks) → tools and RAG; Gate B (budget) → Synthesizer → Verifier; SharedState is read/written by Planner, Executor, Synthesizer, and Verifier.

---

## Architecture Diagram

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e0e7ff', 'primaryTextColor': '#1e293b', 'primaryBorderColor': '#6366f1', 'lineColor': '#64748b', 'secondaryColor': '#f0fdf4', 'tertiaryColor': '#fef3c7'}}}%%

flowchart TB
    subgraph User_Input["👤 User Input"]
        User([User])
        Prompt[/"Free-form travel request"/]
    end

    subgraph ReAct_Loop["🔄 ReAct Loop (Thought → Action → Observation)"]
        direction TB
        
        subgraph Thought["💭 THOUGHT"]
            Supervisor{{"🧠 Supervisor"}}
        end
        
        subgraph Plan["📋 PLAN"]
            Planner["📝 Planner"]
            RAG_Query["🔍 RAG Query"]
        end
        
        subgraph Action["⚡ ACTION"]
            Executor["🚀 Executor"]
        end
    end

    subgraph Synthesis_Phase["✨ Synthesis Phase"]
        GateB["🚧 Gate B<br/>Budget Check"]
        Synthesizer["🎯 Trip Synthesizer"]
        Verifier["✅ Verifier"]
    end

    subgraph Tools["🔧 External Tools"]
        direction LR
        Flights["✈️ Flights API<br/>(Booking.com)"]
        Hotels["🏨 Hotels API<br/>(Booking.com)"]
        Weather["🌤️ Weather API<br/>(Open-Meteo)"]
        POI["📍 POI API<br/>(OpenTripMap)"]
    end

    subgraph RAG_System["🧬 RAG System"]
        Pinecone[("🌲 Pinecone<br/>Wikivoyage")]
    end

    subgraph Data_Layer["💾 Data Layer"]
        SharedState[("📦 SharedState<br/>constraints, flights, hotels,<br/>weather, POIs, RAG chunks, drafts")]
        Supabase[("🗄️ Supabase<br/>Cache | Trips | Sessions | Logs")]
    end

    subgraph LLM_Provider["🤖 LLM Provider"]
        LLM["LLMod.ai<br/>GPT-4o"]
    end

    subgraph Output["📤 Output"]
        Response[/"Trip Packages<br/>with booking links"/]
    end

    %% Main Flow
    User --> Prompt
    Prompt --> Supervisor
    
    %% Supervisor decisions
    Supervisor -->|"plan/replan"| Planner
    Supervisor -->|"clarify"| User
    Supervisor -->|"synthesize"| GateB
    
    %% Planning flow
    Planner --> RAG_Query
    RAG_Query --> Pinecone
    Planner -->|"tasks"| Executor
    
    %% Execution flow
    Executor --> Flights
    Executor --> Hotels
    Executor --> Weather
    Executor --> POI
    Executor -->|"observe results"| Supervisor
    
    %% Tool caching
    Flights -.-> Supabase
    Hotels -.-> Supabase
    
    %% Synthesis flow
    GateB -->|"feasible"| Synthesizer
    GateB -->|"infeasible"| User
    Synthesizer -->|"draft packages"| Verifier
    Verifier -->|"APPROVE"| Response
    Verifier -->|"REJECT"| Supervisor
    
    %% Final output
    Response --> User
    
    %% State connections
    Planner <-.-> SharedState
    Executor <-.-> SharedState
    Synthesizer <-.-> SharedState
    Verifier <-.-> SharedState
    
    %% LLM connections
    Supervisor -.->|"LLM call"| LLM
    Planner -.->|"LLM call"| LLM
    Synthesizer -.->|"LLM call"| LLM
    Verifier -.->|"LLM call"| LLM

    %% Styling
    classDef userStyle fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e40af
    classDef supervisorStyle fill:#ede9fe,stroke:#7c3aed,stroke-width:3px,color:#5b21b6
    classDef planStyle fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e40af
    classDef actionStyle fill:#d1fae5,stroke:#059669,stroke-width:2px,color:#047857
    classDef synthStyle fill:#cffafe,stroke:#0891b2,stroke-width:2px,color:#0e7490
    classDef verifyStyle fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#b45309
    classDef gateStyle fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#b91c1c
    classDef toolStyle fill:#f1f5f9,stroke:#64748b,stroke-width:1px,color:#475569
    classDef dataStyle fill:#f8fafc,stroke:#94a3b8,stroke-width:1px,color:#64748b
    classDef llmStyle fill:#e0e7ff,stroke:#6366f1,stroke-width:2px,color:#4f46e5
    classDef outputStyle fill:#dcfce7,stroke:#22c55e,stroke-width:2px,color:#166534

    class User,Prompt userStyle
    class Supervisor supervisorStyle
    class Planner,RAG_Query planStyle
    class Executor actionStyle
    class Synthesizer synthStyle
    class Verifier verifyStyle
    class GateB gateStyle
    class Flights,Hotels,Weather,POI toolStyle
    class SharedState,Supabase,Pinecone dataStyle
    class LLM llmStyle
    class Response outputStyle
```

---

## Component Details

### Agent Modules (LLM-powered)

| Module | Role | Phase | LLM Calls |
|--------|------|-------|-----------|
| **Supervisor** | Autonomous decision-making brain. Called at every decision point to reason about state and choose next action. | THOUGHT | 1+ per request |
| **Planner** | Extracts constraints from user prompt and generates executable task plan. Uses RAG for destination grounding. | PLAN | 1 per planning cycle |
| **Trip Synthesizer** | Assembles tiered trip packages (Budget/Best Value/Premium) from collected tool data. Uses **RAG chunks from SharedState** (Wikivoyage) to ground itineraries; does not call Pinecone directly. | SYNTHESIS | 1 per synthesis |
| **Verifier** | Audits packages with rule-based checks + LLM quality assessment. Can approve or reject. | REFLECTION | 1 per verification |

### Non-LLM Components

| Component | Role |
|-----------|------|
| **Executor** | Runs tools in parallel using ThreadPoolExecutor. Zero LLM calls. |
| **Gate B** | Deterministic budget feasibility check before synthesis. Zero LLM calls. |
| **SharedState** | Central data store shared by all components. Persists tool results. |

---

## Supervisor Actions

The Supervisor is the decision-making brain called at **every decision point**:

| Action | Description |
|--------|-------------|
| `ask_clarification` | Request missing critical info (e.g., origin city) |
| `plan` | Create initial task plan via Planner |
| `continue` | Execute remaining destination groups |
| `pivot` | Change strategy due to issues (e.g., too expensive) |
| `synthesize` | Build trip packages from collected data |
| `finalize` | Return approved plan to user |
| `replan` | Fix issues after Verifier rejection |

---

## External Services

| Service | Purpose | Cost |
|---------|---------|------|
| **LLMod.ai** | LLM reasoning (GPT-4o) | ~$0.01-0.05/call |
| **Pinecone** | RAG vector DB (Wikivoyage knowledge) | Free tier |
| **Supabase** | Cache, trip storage, session persistence | Free tier |
| **Booking.com API** | Flights + Hotels search | Freemium |
| **Open-Meteo** | Weather forecasts + climate normals | Free |
| **OpenTripMap** | Points of interest | Free |

---

## LLM Budget Management

| Constraint | Value |
|------------|-------|
| Max LLM calls per request | 12 |
| Typical successful run | 5-7 calls |
| Max Supervisor rounds | 8 |
| Budget tolerance | 5% |

### Typical LLM Call Sequence

```
1. Supervisor     → "plan" decision
2. Planner        → constraints + tasks
3. Supervisor     → "continue" (observe Phase 1 results)
4. Supervisor     → "synthesize" (enough data)
5. Synthesizer    → build packages
6. Verifier       → audit and approve
```

---

## Data Flow

```
User Prompt
    │
    ▼
┌─────────────────────────────────────────────────┐
│  SUPERVISOR (observes state, decides action)    │
└─────────────────────────────────────────────────┘
    │                                         ▲
    ▼                                         │
┌─────────────┐      ┌─────────────┐         │
│   PLANNER   │ ──▶  │  EXECUTOR   │ ────────┘
│  +RAG query │      │  (parallel) │    observe
└─────────────┘      └─────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │    TOOLS (Flights,      │
              │    Hotels, Weather,     │
              │    POIs)                │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │     SharedState         │
              │  (persists all data)    │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │   TRIP SYNTHESIZER      │
              │   (builds packages)     │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │      VERIFIER           │
              │   (approves/rejects)    │
              └─────────────────────────┘
                            │
                            ▼
                    Trip Packages
```

---

## What Makes This an Agent

1. **Multi-round Supervisor (ReAct)** - Called 3+ times per request with Thought → Action → Observation cycles
2. **Phased execution** - Searches destinations one at a time, observes results between phases
3. **Adaptive decisions** - Can skip expensive destinations, pivot to cheaper ones based on observations
4. **RAG grounding** - Uses Wikivoyage knowledge to inform destination choices
5. **Self-healing** - On Verifier rejection, loops back for delta replanning
6. **Budget awareness** - Compares prices to budget at every decision point
7. **Scope guard** - Refuses non-travel requests politely
