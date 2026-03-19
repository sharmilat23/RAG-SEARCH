"""
Chat Memory with Supabase Persistence

Replicates the n8n Postgres Chat Memory node behavior:
- Session-based conversation history
- 10-message context window (matching n8n contextWindowLength)
- Persistent storage in Supabase (survives server restarts)
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Lazy-loaded Supabase client
_supabase_client = None

# Table name for chat memory
MEMORY_TABLE = "chat_memory"


def _get_supabase():
    """Get or create the Supabase client (lazy init)"""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
            url = os.environ.get("SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_SERVICE_KEY", "")
            if not url or not key:
                print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set — chat memory will be in-memory only")
                return None
            _supabase_client = create_client(url, key)
            print("✅ Supabase client initialized for chat memory")
        except Exception as e:
            print(f"⚠️  Supabase init failed for chat memory: {e}")
            return None
    return _supabase_client


# In-memory fallback (used when Supabase is unavailable)
_memory_fallback: Dict[str, List[Dict]] = {}

# Context window size — matches n8n Postgres Chat Memory contextWindowLength
CONTEXT_WINDOW = 10


def add_message(session_id: str, role: str, content: str) -> None:
    """
    Store a message in chat history.

    Args:
        session_id: Unique session/conversation identifier
        role: 'user' or 'assistant'
        content: The message text
    """
    message = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    client = _get_supabase()
    if client:
        try:
            client.table(MEMORY_TABLE).insert(message).execute()
            return
        except Exception as e:
            print(f"⚠️  Supabase chat memory insert failed: {e}")
            # Fall through to in-memory fallback

    # In-memory fallback
    if session_id not in _memory_fallback:
        _memory_fallback[session_id] = []
    _memory_fallback[session_id].append(message)


def get_history(session_id: str, limit: int = CONTEXT_WINDOW) -> List[Dict]:
    """
    Retrieve recent chat history for a session.

    Args:
        session_id: Unique session/conversation identifier
        limit: Max messages to return (default: 10, matching n8n)

    Returns:
        List of {role, content} dicts in chronological order
    """
    client = _get_supabase()
    if client:
        try:
            result = (
                client.table(MEMORY_TABLE)
                .select("role, content")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .execute()
            )
            messages = result.data or []
            # Return only the last `limit` messages
            return messages[-limit:]
        except Exception as e:
            print(f"⚠️  Supabase chat memory read failed: {e}")
            # Fall through to in-memory

    # In-memory fallback
    messages = _memory_fallback.get(session_id, [])
    return [{"role": m["role"], "content": m["content"]} for m in messages[-limit:]]


def clear_session(session_id: str) -> None:
    """Clear all messages for a session."""
    client = _get_supabase()
    if client:
        try:
            client.table(MEMORY_TABLE).delete().eq("session_id", session_id).execute()
        except Exception as e:
            print(f"⚠️  Supabase chat memory clear failed: {e}")

    # Also clear in-memory fallback
    _memory_fallback.pop(session_id, None)


def format_history_for_prompt(session_id: str) -> str:
    """
    Format chat history as a string for LLM prompt context.

    Returns:
        Formatted string of recent conversation, or empty string if no history.
    """
    history = get_history(session_id)
    if not history:
        return ""

    lines = []
    for msg in history:
        prefix = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{prefix}: {msg['content']}")

    return "\n".join(lines)
