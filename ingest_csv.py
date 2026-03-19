"""
CSV → Supabase Ingestion Script

Reads tools from futuretools_full_safe_with_tags.csv, generates Google Gemini embeddings,
and stores them in the Supabase 'documents' table for RAG retrieval.

Handles Google free-tier rate limits: 100 req/min → pauses automatically.
Supports resuming: skips tools already in the database.
"""

import os
import csv
import time
import json
import sys

# Load env vars from .env file
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# ── Config ──
CSV_FILE = os.path.join(os.path.dirname(__file__), 'futuretools_full_safe_with_tags.csv')
SUPABASE_TABLE = 'documents'
GEMINI_MODEL = 'models/gemini-embedding-001'
RATE_LIMIT_BATCH = 80   # Pause after this many requests (free tier = 100/min)
RATE_LIMIT_PAUSE = 62   # Seconds to pause (just over 1 minute)
MAX_RETRIES = 3


def get_supabase():
    from supabase import create_client
    url = os.environ.get('SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)
    return create_client(url, key)


def get_embedding(text, retry=0):
    """Generate embedding using Google Gemini, with rate-limit retry"""
    import google.generativeai as genai
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if not api_key:
        print("ERROR: GOOGLE_API_KEY must be set in .env")
        sys.exit(1)
    genai.configure(api_key=api_key)
    try:
        result = genai.embed_content(
            model=GEMINI_MODEL,
            content=text,
            task_type="retrieval_document"
        )
        return result["embedding"]
    except Exception as e:
        if '429' in str(e) and retry < MAX_RETRIES:
            wait = RATE_LIMIT_PAUSE
            print(f"   ... Rate limited, waiting {wait}s (retry {retry+1}/{MAX_RETRIES})")
            time.sleep(wait)
            return get_embedding(text, retry + 1)
        raise


def build_document_content(row):
    """Build a rich text representation of a tool for embedding."""
    parts = []
    name = row.get('name', '').strip()
    if name:
        parts.append(f"Tool: {name}")
    desc = row.get('description', '').strip()
    if desc:
        parts.append(f"Description: {desc}")
    long_desc = row.get('long_description', '').strip()
    if long_desc:
        parts.append(f"Details: {long_desc}")
    categories = row.get('categories', '').strip()
    if categories:
        parts.append(f"Categories: {categories}")
    pricing = row.get('pricing', '').strip()
    if pricing:
        parts.append(f"Pricing: {pricing}")
    tags = row.get('tags', '').strip()
    if tags:
        parts.append(f"Tags: {tags}")
    website = row.get('website', '').strip()
    if website:
        parts.append(f"Website: {website}")
    return "\n".join(parts)


def build_metadata(row):
    """Build metadata JSON for the document"""
    return {
        "name": row.get('name', '').strip(),
        "slug": row.get('slug', '').strip(),
        "categories": row.get('categories', '').strip(),
        "pricing": row.get('pricing', '').strip(),
        "website": row.get('website', '').strip(),
        "external_url": row.get('external_url', '').strip(),
        "tags": row.get('tags', '').strip(),
        "source": "futuretools_csv"
    }


def get_existing_slugs(client):
    """Get slugs already in the database to support resume"""
    try:
        result = client.table(SUPABASE_TABLE).select("metadata").execute()
        slugs = set()
        for row in (result.data or []):
            meta = row.get('metadata')
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except:
                    continue
            if isinstance(meta, dict):
                slug = meta.get('slug', '')
                if slug:
                    slugs.add(slug)
        return slugs
    except:
        return set()


def main():
    print("=" * 60)
    print("  CSV -> Supabase Ingestion (RAG Pipeline)")
    print("  Rate limit: pause every %d tools for %ds" % (RATE_LIMIT_BATCH, RATE_LIMIT_PAUSE))
    print("=" * 60)

    # Read CSV
    print("\n Reading %s..." % os.path.basename(CSV_FILE))
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print("   Found %d tools" % len(rows))

    # Connect to Supabase
    print("\n Connecting to Supabase...")
    client = get_supabase()
    print("   Connected")

    # Check for existing data (resume support)
    print("\n Checking for existing data...")
    existing_slugs = get_existing_slugs(client)
    if existing_slugs:
        print("   Found %d tools already ingested - will skip them" % len(existing_slugs))
    else:
        print("   No existing data - starting fresh")

    # Ingest tools
    total = len(rows)
    print("\n Starting ingestion (%d tools, %d to skip)..." % (total, len(existing_slugs)))

    success_count = 0
    skip_count = 0
    error_count = 0
    batch_count = 0  # Track API calls for rate limiting
    start_time = time.time()

    for i, row in enumerate(rows):
        name = row.get('name', 'Unknown').strip()
        slug = row.get('slug', '').strip()

        # Skip already-ingested tools
        if slug in existing_slugs:
            skip_count += 1
            continue

        content = build_document_content(row)
        metadata = build_metadata(row)

        if not content or len(content) < 20:
            skip_count += 1
            continue

        # Rate limit: pause before hitting the limit
        if batch_count > 0 and batch_count % RATE_LIMIT_BATCH == 0:
            print("   ... Pausing %ds for rate limit (batch %d)..." % (RATE_LIMIT_PAUSE, batch_count // RATE_LIMIT_BATCH))
            time.sleep(RATE_LIMIT_PAUSE)

        try:
            # Generate embedding
            embedding = get_embedding(content)
            batch_count += 1

            # Insert into Supabase
            doc = {
                "content": content,
                "metadata": json.dumps(metadata),
                "embedding": embedding
            }
            client.table(SUPABASE_TABLE).insert(doc).execute()

            success_count += 1
            if success_count % 50 == 0 or (i + 1) == total:
                elapsed = time.time() - start_time
                rate = success_count / elapsed if elapsed > 0 else 0
                eta_min = (total - i - 1) / (rate * 60) if rate > 0 else 0
                print("   [%d/%d] %s | %d done | %.1f/sec | ETA: %.0f min" % (
                    i + 1, total, name, success_count, rate, eta_min))

        except Exception as e:
            error_count += 1
            err_str = str(e)[:100]
            print("   FAIL [%d/%d] '%s': %s" % (i + 1, total, name, err_str))
            if error_count >= 20:
                print("\n   Too many errors. Stopping.")
                break
            time.sleep(2)

    # Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("  INGESTION COMPLETE")
    print("  Inserted: %d" % success_count)
    print("  Skipped:  %d" % skip_count)
    print("  Failed:   %d" % error_count)
    print("  Time:     %.1fs (%.1f min)" % (elapsed, elapsed / 60))
    print("=" * 60)


if __name__ == '__main__':
    main()
