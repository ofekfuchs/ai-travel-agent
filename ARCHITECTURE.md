# AI Travel Agent - Architecture Diagram

```mermaid
graph TD
    Start((Start)) --> User["User Input"]
    User --> Supervisor{"Supervisor"}

    Supervisor -- "clarify" --> User

    subgraph ReAct_Loop["ReAct Loop"]
        direction TB
        Supervisor -- "plan" --> Planner["Planner"]
        Planner -- "tasks" --> Executor["Executor"]
        Executor -- "observe" --> Decide{"Continue?"}
        Decide -- "YES" --> Executor
        Decide -- "NO" --> Supervisor
    end

    subgraph Synthesis_Phase["Synthesis Phase"]
        Supervisor -- "synthesize" --> Synth["Synthesizer"]
        Synth -- "draft" --> Verifier["Verifier"]
        Verifier -- "APPROVE" --> Final["Final Response"]
        Verifier -- "REJECT" --> Supervisor
    end

    subgraph Tools["External Tools"]
        direction LR
        Flights["Flights API"]
        Hotels["Hotels API"]
        Weather["Weather API"]
        POI["POI API"]
        RAG["RAG"]
    end

    subgraph Data["Data Layer"]
        State[("Shared State")]
        Cache[("Cache")]
    end

    Executor --> Flights
    Executor --> Hotels
    Executor --> Weather
    Executor --> POI
    Executor --> RAG

    Flights -.-> Cache
    Hotels -.-> Cache

    Planner <-.-> State
    Executor <-.-> State
    Synth <-.-> State
    Verifier <-.-> State

    Final --> End((End))

    classDef startEnd fill:#d4edda,stroke:#28a745,color:#155724
    classDef user fill:#fff3cd,stroke:#ffc107,color:#856404
    classDef supervisor fill:#cce5ff,stroke:#007bff,color:#004085
    classDef agent fill:#e2e3e5,stroke:#6c757d,color:#383d41
    classDef tool fill:#f8f9fa,stroke:#adb5bd,color:#495057
    classDef data fill:#fff,stroke:#dee2e6,color:#6c757d
    classDef decision fill:#d1ecf1,stroke:#17a2b8,color:#0c5460

    class Start,End startEnd
    class User,Final user
    class Supervisor supervisor
    class Planner,Executor,Synth,Verifier agent
    class Flights,Hotels,Weather,POI,RAG tool
    class State,Cache data
    class Decide decision
```

## Architecture Overview

### Components

| Component | Role | Phase |
|-----------|------|-------|
| **Supervisor** | Autonomous decision-making brain. Called at every decision point. | THOUGHT |
| **Planner** | Extracts constraints and generates executable tasks. | PLAN |
| **Executor** | Runs tasks in parallel using ThreadPoolExecutor. | ACTION |
| **Trip Synthesizer** | Assembles trip packages from collected data. | SYNTHESIS |
| **Verifier** | Audits packages with rule-based and LLM checks. | REFLECTION |
| **SharedState** | Central data store shared by all components. | - |

### Supervisor Actions

| Action | Description |
|--------|-------------|
| `ask_clarification` | Request missing info from user |
| `plan` | Create initial task plan |
| `continue` | Execute remaining destination groups |
| `pivot` | Change strategy due to issues |
| `synthesize` | Build trip packages |
| `finalize` | Return approved plan to user |
| `replan` | Fix issues after Verifier rejection |

### Tools

| Tool | Purpose |
|------|---------|
| Flights API | Search flight options |
| Hotels API | Search hotel options |
| Weather API | Get weather forecasts |
| POI API | Find points of interest |
| RAG (Pinecone) | Retrieve destination knowledge |
| Cache (Supabase) | Store and reuse API results |

### Constraints

- Maximum 6 ReAct loop iterations
- Maximum 8 LLM calls per session
- Budget validation via Gate B before synthesis
