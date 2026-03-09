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
# Agent behaviour constants
# ---------------------------------------------------------------------------
# The Supervisor-driven agentic loop is configured in main.py:
#   MAX_SUPERVISOR_ROUNDS = 6  (max decision points per request)
#   LLM_CALL_CAP = 8          (hard cap, defined in shared_state.py)
