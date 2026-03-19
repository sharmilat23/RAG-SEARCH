"""
Setup Supabase tables via REST API + run checks.
Uses the service_role key which has full access.
"""
import os
import sys
import json

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

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

import httpx

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

print("=" * 60)
print("  Supabase Table Check")
print("=" * 60)

# 1. Check if 'documents' table exists
print("\n1. Checking 'documents' table...")
r = httpx.get(f"{SUPABASE_URL}/rest/v1/documents?select=id&limit=1", headers=headers)
if r.status_code == 200:
    data = r.json()
    print(f"   OK - 'documents' table exists ({len(data)} rows returned)")
elif r.status_code == 404 or (r.status_code >= 400 and 'relation' in r.text.lower()):
    print(f"   NOT FOUND - 'documents' table does not exist")
    print(f"   Response: {r.status_code} {r.text[:200]}")
else:
    print(f"   Response: {r.status_code} {r.text[:300]}")

# 2. Check if 'chat_memory' table exists
print("\n2. Checking 'chat_memory' table...")
r2 = httpx.get(f"{SUPABASE_URL}/rest/v1/chat_memory?select=id&limit=1", headers=headers)
if r2.status_code == 200:
    data2 = r2.json()
    print(f"   OK - 'chat_memory' table exists ({len(data2)} rows returned)")
elif r2.status_code == 404 or (r2.status_code >= 400 and 'relation' in r2.text.lower()):
    print(f"   NOT FOUND - 'chat_memory' table does not exist")
    print(f"   Response: {r2.status_code} {r2.text[:200]}")
else:
    print(f"   Response: {r2.status_code} {r2.text[:300]}")

# 3. Check if 'match_documents' RPC exists
print("\n3. Checking 'match_documents' RPC...")
r3 = httpx.post(f"{SUPABASE_URL}/rest/v1/rpc/match_documents", headers=headers, json={
    "query_embedding": [0.0] * 768,
    "match_count": 1
})
if r3.status_code == 200:
    print(f"   OK - 'match_documents' RPC exists and works")
elif r3.status_code == 404:
    print(f"   NOT FOUND - 'match_documents' function does not exist")
else:
    print(f"   Response: {r3.status_code} {r3.text[:300]}")

print("\n" + "=" * 60)
print("  Done. See results above.")
print("=" * 60)
