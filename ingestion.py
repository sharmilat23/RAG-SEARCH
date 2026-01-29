from models import db, Tool

def ingest_tool(data):
    """
    Single source of truth for adding tools.
    Generates semantic search embedding for new tools.
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

    # Generate embedding for semantic search
    try:
        from semantic_search import get_search_engine
        engine = get_search_engine()
        if engine:
            engine.index_single_tool(tool)
            print(f"✅ Generated embedding for tool: {tool.name}")
    except Exception as e:
        print(f"⚠️  Could not generate embedding for {tool.name}: {e}")
        # Continue without embedding - can be generated later

    db.session.commit()

    return {"status": "added", "id": tool.id}, True

