"""
Generate embeddings for all existing tools in the database.

Usage:
    python scripts/generate_embeddings.py

This script will:
1. Load all tools from the database
2. Generate embeddings using sentence-transformers
3. Store embeddings in the database
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Tool
from semantic_search import get_search_engine


def main():
    print("=" * 60)
    print("GENERATING EMBEDDINGS FOR ALL TOOLS")
    print("=" * 60)
    
    with app.app_context():
        # Count tools
        tool_count = Tool.query.count()
        print(f"\nFound {tool_count} tools in database")
        
        if tool_count == 0:
            print("No tools to index. Add some tools first!")
            return
        
        # Get search engine
        print("\nInitializing semantic search engine...")
        engine = get_search_engine()
        
        # Reindex all tools
        print("\nGenerating embeddings (this may take a moment)...")
        indexed = engine.reindex_all_tools()
        
        print("\n" + "=" * 60)
        print(f"✅ SUCCESS: Generated embeddings for {indexed} tools")
        print("=" * 60)
        
        # Verify a few tools have embeddings
        print("\nVerifying embeddings...")
        sample_tools = Tool.query.limit(3).all()
        for tool in sample_tools:
            has_embedding = bool(tool.embedding and len(tool.embedding) > 10)
            status = "✅" if has_embedding else "❌"
            print(f"  {status} {tool.name}: embedding={'yes' if has_embedding else 'no'}")


if __name__ == "__main__":
    main()
