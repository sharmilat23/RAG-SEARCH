"""
RAG Pipeline — Python equivalent of the n8n workflow

Replicates the EXACT n8n workflow behavior:
  1. Chat Trigger          →  Flask route (in app.py)
  2. Embeddings Gemini     →  google-generativeai SDK
  3. Supabase Vector Store →  supabase-py + match_documents RPC
  4. Mistral Cloud Chat    →  mistralai SDK
  5. AI Agent              →  build_prompt + generate_response
  6. Postgres Chat Memory  →  chat_memory.py module

Key config from n8n workflow:
  - Embedding model: Google Gemini (gemini-embedding-001)
  - Vector store: Supabase table "documents", top_k = 5
  - LLM: Mistral Cloud (mistral-small-latest)
  - Memory: 10-message context window
  - Tool description: "Search through AI tools database for features, pricing, and use cases"
"""

import os
import json
from typing import List, Dict, Optional, Tuple

# Lazy-loaded clients
_supabase_client = None
_mistral_client = None
_gemini_configured = False

# ──────────────────────────────────────────────
# Config — matches n8n workflow exactly
# ──────────────────────────────────────────────
SUPABASE_TABLE = "documents"  # n8n: tableName = "documents"
TOP_K = 5                     # n8n: topK = 5
MISTRAL_MODEL = "mistral-small-latest"  # n8n: default Mistral model
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"  # n8n: Gemini embedding (updated)

# System prompt — replicates the n8n AI Agent node behavior
# The n8n agent uses "retrieve-as-tool" with this tool description
TOOL_DESCRIPTION = "Search through AI tools database for features, pricing, and use cases"

SYSTEM_PROMPT = """You are an AI tool recommendation assistant for a tools directory website.

CRITICAL RULES (you MUST follow these — violations are unacceptable):
1. You may ONLY recommend or mention tools that appear in the "RETRIEVED TOOLS FROM DATABASE" section below.
2. NEVER invent, fabricate, or recall tools from your own training data. If a tool is not listed below, you do not know about it.
3. NEVER fabricate reviews, ratings, star counts, or review numbers. You do not have access to reviews data.
4. If the retrieved tools are not a perfect match for the user's query, DO NOT say "I couldn't find a matching tool." Instead, suggest the closest retrieved tools and explain how they might partially help the user achieve their goal.
5. When recommending tools, use ONLY the name, description, categories, pricing, tags, and website URL from the data below.
6. Suggest tools and explain WHY they fit the user's needs based on the tool's actual description and tags.
7. Compare tools when asked — but only compare tools from the list below.
8. Give step-by-step workflows when appropriate, using only the tools below.
9. Be concise but thorough.

Remember: You are a search interface for our database, NOT a general AI assistant. Stay grounded."""


# ──────────────────────────────────────────────
# Client initialization (lazy)
# ──────────────────────────────────────────────

def _get_supabase():
    """Get or create Supabase client"""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_SERVICE_KEY", "")
            if not url or not key:
                print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not configured")
                return None
            _supabase_client = create_client(url, key)
            print("✅ Supabase client initialized for RAG pipeline")
        except Exception as e:
            print(f"⚠️  Supabase init failed: {e}")
            return None
    return _supabase_client


def _get_mistral():
    """Get or create Mistral client"""
    global _mistral_client
    if _mistral_client is None:
        try:
            from mistralai.client import Mistral
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            if not api_key:
                print("⚠️  MISTRAL_API_KEY not configured")
                return None
            _mistral_client = Mistral(api_key=api_key)
            print("✅ Mistral client initialized")
        except Exception as e:
            print(f"⚠️  Mistral init failed: {e}")
            return None
    return _mistral_client


def _configure_gemini():
    """Configure Google Gemini for embeddings"""
    global _gemini_configured
    if not _gemini_configured:
        try:
            import google.generativeai as genai
            api_key = os.environ.get("GOOGLE_API_KEY", "")
            if not api_key:
                print("⚠️  GOOGLE_API_KEY not configured")
                return False
            genai.configure(api_key=api_key)
            _gemini_configured = True
            print("✅ Google Gemini configured for embeddings")
        except Exception as e:
            print(f"⚠️  Gemini config failed: {e}")
            return False
    return True


# ──────────────────────────────────────────────
# Embedding (replicates: Embeddings Google Gemini node)
# ──────────────────────────────────────────────

def get_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding using Google Gemini.
    Replicates: n8n "Embeddings Google Gemini1" node
    """
    if not _configure_gemini():
        return None
    try:
        import google.generativeai as genai
        result = genai.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_query"
        )
        return result["embedding"]
    except Exception as e:
        print(f"❌ Gemini embedding failed: {e}")
        return None


# ──────────────────────────────────────────────
# Retrieval (replicates: Supabase Vector Store — Retrieve as Tool)
# ──────────────────────────────────────────────

def retrieve_documents(query: str, top_k: int = TOP_K) -> List[Dict]:
    """
    Retrieve relevant documents from Supabase vector store.

    Replicates: n8n "Supabase Vector Store - Retrieve as Tool" node
      - Table: "documents"
      - top_k: 5
      - Uses Google Gemini embeddings for the query

    Args:
        query: User's search query
        top_k: Number of documents to retrieve (default: 5)

    Returns:
        List of document dicts with 'content' and 'metadata' fields
    """
    # Step 1: Get query embedding
    query_embedding = get_embedding(query)
    if query_embedding is None:
        print("⚠️  Could not generate query embedding, skipping retrieval")
        return []

    # Step 2: Call Supabase match_documents RPC
    client = _get_supabase()
    if client is None:
        return []

    try:
        result = client.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_count": top_k
            }
        ).execute()

        documents = result.data or []
        print(f"📄 Retrieved {len(documents)} documents from Supabase")
        # Debug: show which tools were retrieved
        for i, doc in enumerate(documents):
            meta = doc.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except:
                    meta = {}
            name = meta.get("name", "Unknown")
            sim = doc.get("similarity", 0)
            print(f"   📌 [{i+1}] {name} (similarity: {sim:.3f})")
        return documents

    except Exception as e:
        print(f"❌ Supabase retrieval failed: {e}")
        # Try direct table query as fallback
        try:
            result = (
                client.table(SUPABASE_TABLE)
                .select("content, metadata")
                .limit(top_k)
                .execute()
            )
            print(f"📄 Fallback: retrieved {len(result.data or [])} documents")
            return result.data or []
        except Exception as e2:
            print(f"❌ Fallback retrieval also failed: {e2}")
            return []


# ──────────────────────────────────────────────
# Prompt building (replicates: AI Agent node logic)
# ──────────────────────────────────────────────

def build_prompt(
    query: str,
    context_docs: List[Dict],
    chat_history: str = ""
) -> List[Dict]:
    """
    Build the message array for the Mistral LLM.

    Replicates the n8n AI Agent node's prompt construction:
    - System prompt with tool description context
    - Retrieved documents as context
    - Conversation history from Postgres Chat Memory
    - Current user query

    Args:
        query: Current user question
        context_docs: Retrieved documents from Supabase
        chat_history: Formatted conversation history string

    Returns:
        List of message dicts for the Mistral API
    """
    # Build context from retrieved documents — format each tool clearly
    context_parts = []
    for i, doc in enumerate(context_docs, 1):
        content = doc.get("content", "")
        metadata = doc.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        # Extract structured fields for clarity
        name = metadata.get("name", "Unknown Tool")
        categories = metadata.get("categories", "")
        pricing = metadata.get("pricing", "")
        website = metadata.get("website", "") or metadata.get("external_url", "")
        tags = metadata.get("tags", "")
        similarity = doc.get("similarity", None)
        score_str = f" | Relevance: {similarity:.2f}" if similarity else ""

        # Build a structured tool card
        tool_card = f"""--- TOOL {i}: {name}{score_str} ---
{content}
Website: {website}
Pricing: {pricing}
Categories: {categories}
Tags: {tags}"""
        context_parts.append(tool_card)

    if context_parts:
        context_text = "\n\n".join(context_parts)
    else:
        context_text = "NO TOOLS FOUND IN DATABASE. Tell the user you couldn't find matching tools."

    # Build system message
    system_content = SYSTEM_PROMPT + f"\n\n========== RETRIEVED TOOLS FROM DATABASE ==========\n{context_text}\n========== END OF RETRIEVED TOOLS =========="

    if chat_history:
        system_content += f"\n\n--- Previous Conversation ---\n{chat_history}"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": query}
    ]

    return messages


# ──────────────────────────────────────────────
# LLM generation (replicates: Mistral Cloud Chat Model node)
# ──────────────────────────────────────────────

def call_mistral(messages: List[Dict]) -> str:
    """
    Call Mistral Cloud LLM.
    Replicates: n8n "Mistral Cloud Chat Model" node (default settings)

    Args:
        messages: Message array for the chat API

    Returns:
        Generated text response
    """
    client = _get_mistral()
    if client is None:
        return "I'm sorry, the AI service is currently unavailable. Please try again later."

    try:
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Mistral API call failed: {e}")
        return f"I encountered an error generating a response. Please try again. (Error: {type(e).__name__})"


# ──────────────────────────────────────────────
# Full pipeline (replicates: entire n8n workflow)
# ──────────────────────────────────────────────

def generate_response(query: str, session_id: str) -> str:
    """
    Full RAG pipeline — exact replica of the n8n workflow.

    Flow:
      1. Get conversation history (Postgres Chat Memory)
      2. Embed query (Google Gemini)
      3. Retrieve documents (Supabase Vector Store, top_k=5)
      4. Build prompt (AI Agent)
      5. Generate response (Mistral Cloud)
      6. Store messages in memory

    Args:
        query: User's question
        session_id: Session identifier for conversation memory

    Returns:
        LLM-generated response string
    """
    import chat_memory

    # Step 1: Get conversation history
    chat_history = chat_memory.format_history_for_prompt(session_id)

    # Step 2 & 3: Retrieve relevant documents (embedding happens inside)
    context_docs = retrieve_documents(query)

    # Step 4: Build the prompt
    messages = build_prompt(query, context_docs, chat_history)

    # Step 5: Generate response with Mistral
    response = call_mistral(messages)

    # Step 6: Store both messages in conversation memory
    chat_memory.add_message(session_id, "user", query)
    chat_memory.add_message(session_id, "assistant", response)

    return response
