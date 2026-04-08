"""
Sync all tools from app database into Supabase documents vector store.

Usage:
    python scripts/generate_embeddings.py

This script will:
1. Load all tools from the app database
2. Generate embeddings using Google Gemini
3. Upsert records into Supabase documents table
"""

import sys
import os
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import Tool
from supabase import create_client
import google.generativeai as genai


def build_document_content(tool: Tool) -> str:
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


def parse_metadata(meta):
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str):
        try:
            return json.loads(meta)
        except Exception:
            return {}
    return {}


def main():
    print("=" * 60)
    print("SYNCING TOOLS TO SUPABASE VECTOR STORE")
    print("=" * 60)

    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    google_key = os.environ.get("GOOGLE_API_KEY", "")

    if not supabase_url or not supabase_key or not google_key:
        print("ERROR: SUPABASE_URL, SUPABASE_SERVICE_KEY and GOOGLE_API_KEY are required")
        return

    client = create_client(supabase_url, supabase_key)
    genai.configure(api_key=google_key)

    with app.app_context():
        tools = Tool.query.order_by(Tool.id.asc()).all()
        print(f"Found {len(tools)} tools in app DB")

        existing = client.table("documents").select("id, metadata").execute()
        existing_by_tool_id = {}
        for row in (existing.data or []):
            meta = parse_metadata(row.get("metadata"))
            tool_id = meta.get("tool_id")
            if tool_id is not None:
                existing_by_tool_id[str(tool_id)] = row.get("id")

        inserted = 0
        updated = 0
        failed = 0

        for idx, tool in enumerate(tools, 1):
            try:
                content = build_document_content(tool)
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

                payload = {
                    "content": content,
                    "metadata": json.dumps(metadata),
                    "embedding": embedding,
                }

                existing_id = existing_by_tool_id.get(str(tool.id))
                if existing_id:
                    client.table("documents").update(payload).eq("id", existing_id).execute()
                    updated += 1
                else:
                    client.table("documents").insert(payload).execute()
                    inserted += 1

                if idx % 25 == 0 or idx == len(tools):
                    print(f"[{idx}/{len(tools)}] inserted={inserted} updated={updated} failed={failed}")

            except Exception as e:
                failed += 1
                print(f"FAIL: {tool.name} -> {e}")

    print("=" * 60)
    print(f"DONE inserted={inserted} updated={updated} failed={failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
