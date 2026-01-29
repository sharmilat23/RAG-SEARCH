"""
Test script for the /internal/tools/ingest endpoint
Sends a POST request and verifies the tool was inserted into the database
"""
import requests
import json
from app import app
from models import db, Tool

def test_ingestion_endpoint():
    """Test the ingestion endpoint with a sample tool"""
    
    # Test data
    test_tool = {
        "name": "Test AI Tool",
        "website": "https://testaitool.com",
        "short_description": "A test tool for verification",
        "description": "This is a test tool to verify the ingestion endpoint is working correctly.",
        "category": "Testing",
        "pricing": "Free",
        "logo": "🧪",
        "tags": ["test", "verification"]
    }
    
    print("=" * 60)
    print("TESTING INGESTION ENDPOINT")
    print("=" * 60)
    
    # Send POST request
    print("\n1. Sending POST request to /internal/tools/ingest...")
    try:
        response = requests.post(
            'http://localhost:5000/internal/tools/ingest',
            json=test_tool,
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.json()}")
        
        if response.status_code == 201:
            print("   ✅ SUCCESS: Tool ingested (HTTP 201)")
        elif response.status_code == 400:
            print("   ⚠️  WARNING: Tool already exists or validation failed (HTTP 400)")
        else:
            print(f"   ❌ UNEXPECTED: Received status code {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ ERROR: Failed to send request - {e}")
        return False
    
    # Verify in database
    print("\n2. Verifying tool in database...")
    with app.app_context():
        tool = Tool.query.filter_by(name="Test AI Tool").first()
        
        if tool:
            print("   ✅ SUCCESS: Tool found in database!")
            print(f"   - Name: {tool.name}")
            print(f"   - Website: {tool.website}")
            print(f"   - Category: {tool.category}")
            print(f"   - Pricing: {tool.pricing}")
            print(f"   - Logo: {tool.logo}")
            print(f"   - Short Description: {tool.short_description}")
            
            # Count total tools
            total_tools = Tool.query.count()
            print(f"\n   Total tools in database: {total_tools}")
            
            print("\n" + "=" * 60)
            print("✅ INGESTION ENDPOINT TEST PASSED")
            print("=" * 60)
            return True
        else:
            print("   ❌ FAILED: Tool not found in database")
            print("\n" + "=" * 60)
            print("❌ INGESTION ENDPOINT TEST FAILED")
            print("=" * 60)
            return False

if __name__ == "__main__":
    test_ingestion_endpoint()
