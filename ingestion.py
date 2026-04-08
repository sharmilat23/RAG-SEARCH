import os
import json

from models import db, Tool


def _build_rag_content(tool: Tool) -> str:
    parts = [
        f"Tool: {tool.name}",
        f"Description: {tool.short_description or ''}",
        f"Details: {tool.description or ''}",
        f"Categories: {tool.category or ''}",
        f"Pricing: {tool.pricing or ''}",
        f"Tags: {tool.tags or ''}",
        f"Website: {tool.website or ''}",
    ]
    return "\n".join([p for p in parts if p.strip()])


def _sync_tool_to_rag(tool: Tool) -> None:
    """Index a tool in the Supabase documents table used by chatbot RAG."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not url or not key or not api_key:
        print("⚠️  Skipping RAG sync: missing SUPABASE_URL/SUPABASE_SERVICE_KEY/GOOGLE_API_KEY")
        return

    from supabase import create_client
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    content = _build_rag_content(tool)
    embedding = genai.embed_content(
        model="models/gemini-embedding-001",
        content=content,
        task_type="retrieval_document"
    )["embedding"]

    metadata = {
        "tool_id": tool.id,
        "name": tool.name,
        "categories": tool.category or "",
        "pricing": tool.pricing or "",
        "website": tool.website or "",
        "tags": tool.tags or "",
        "source": "app_db",
    }

    client = create_client(url, key)
    existing = (
        client.table("documents")
        .select("id, metadata")
        .execute()
    )

    doc_id = None
    for row in (existing.data or []):
        meta = row.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if isinstance(meta, dict) and str(meta.get("tool_id", "")) == str(tool.id):
            doc_id = row.get("id")
            break

    payload = {
        "content": content,
        "metadata": json.dumps(metadata),
        "embedding": embedding,
    }

    if doc_id:
        client.table("documents").update(payload).eq("id", doc_id).execute()
    else:
        client.table("documents").insert(payload).execute()

def ingest_tool(data):
    """
    Single source of truth for adding tools.
    Adds tool to SQL DB and indexes it into chatbot RAG vector store.
    """

    # Validation
    if "name" not in data or "website" not in data:
        return {"error": "Name and website required"}, False

    # Duplicate check
    if Tool.query.filter_by(name=data["name"]).first():
        return {"error": "Tool already exists"}, False

    # Create tool
    tool = Tool(
        name=data["name"],
        short_description=data.get("short_description", ""),
        description=data.get("description", ""),
        category=data.get("category", "Other"),
        pricing=data.get("pricing", "Unknown"),
        website=data["website"],
        logo=data.get("logo", "🔧"),
        tags=",".join(data.get("tags", [])),
        features="[]"
    )

    db.session.add(tool)
    db.session.flush()  # Get the tool ID before generating embedding

    # Sync to chatbot RAG vector store (Supabase documents)
    try:
        _sync_tool_to_rag(tool)
        print(f"✅ Synced tool to RAG documents: {tool.name}")
    except Exception as e:
        print(f"⚠️  Could not sync RAG document for {tool.name}: {e}")
        # Continue without blocking tool creation

    db.session.commit()

    return {"status": "added", "id": tool.id}, True

