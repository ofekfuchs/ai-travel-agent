import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LLM (LLMod.ai) – accessed via LangChain ChatOpenAI with a custom base URL
# ---------------------------------------------------------------------------
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.llmod.ai/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "")

# ---------------------------------------------------------------------------
# Pinecone (vector DB for Wikivoyage RAG)
# ---------------------------------------------------------------------------
PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT: str = os.getenv("PINECONE_ENVIRONMENT", "")
PINECONE_INDEX_NAME: str = os.getenv("PINECONE_INDEX_NAME", "wikivoyage-index")

# ---------------------------------------------------------------------------
# Supabase (primary DB – caching, session traces)
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

# ---------------------------------------------------------------------------
# External tool APIs
# ---------------------------------------------------------------------------
RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")
OPENTRIPMAP_API_KEY: str = os.getenv("OPENTRIPMAP_API_KEY", "")

# ---------------------------------------------------------------------------
# RAG hyperparameters (all RAG tuning in one place)
# ---------------------------------------------------------------------------

# Retrieval
RAG_TOP_K: int = 5                     # chunks returned per Pinecone query
RAG_SCORE_THRESHOLD: float = 0.3       # ignore chunks below this cosine similarity

# Chunk storage (ingestion)
RAG_MAX_CHUNK_CHARS: int = 2000        # max chars per chunk stored in Pinecone
RAG_MIN_SECTION_CHARS: int = 50        # skip sections shorter than this
RAG_UPSERT_BATCH_SIZE: int = 50        # vectors per Pinecone upsert call

# Chunk display (how much content agents see — controls LLM token usage)
RAG_DISPLAY_CHARS_PLANNER: int = 200   # chars of chunk content shown to Planner
RAG_DISPLAY_CHARS_SYNTH: int = 300     # chars of chunk content shown to Synthesizer
RAG_MAX_CHUNKS_PLANNER: int = 5        # max chunks included in Planner prompt
RAG_MAX_CHUNKS_SYNTH: int = 3          # max chunks per destination for Synthesizer
RAG_MAX_CHUNKS_GATE_B: int = 3         # max chunks in Gate B response

# Cost estimation (for dry-run mode in seed script)
RAG_COST_PER_1K_TOKENS: float = 0.00002   # embedding cost
RAG_AVG_TOKENS_PER_CHUNK: int = 350        # conservative estimate after 2000-char cap

# Sections to extract from Wikivoyage articles
RAG_RELEVANT_SECTIONS: set[str] = {
    "understand", "get in", "get around", "see", "do", "eat", "drink",
    "sleep", "buy", "stay safe", "cope", "respect", "connect",
    "budget", "climate", "when to go",
}

# ---------------------------------------------------------------------------
# Agent behaviour constants
# ---------------------------------------------------------------------------
# The Supervisor-driven agentic loop is configured in main.py:
#   MAX_SUPERVISOR_ROUNDS = 8  (max decision points per request)
#   LLM_CALL_CAP = 12         (hard cap, defined in shared_state.py)
