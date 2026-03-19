"""
Seed SQLite database with tools from the FutureTools CSV file.
Replaces the old sample_data.py.
"""

import csv
import os
import json
import random


# Category → emoji mapping
CATEGORY_ICONS = {
    'Productivity': '⚡', 'Chat': '💬', 'Marketing': '📢', 'Music': '🎵',
    'Generative Art': '🎨', 'Research': '🔬', 'Finance': '💰', 'Gaming': '🎮',
    'Video Editing': '🎬', 'Copywriting': '✍️', 'Text-To-Speech': '🗣️',
    'Image Improvement': '🖼️', 'Self-Improvement': '🌱', 'Social Media': '📱',
    'Automation & Agents': '🤖', 'For Fun': '🎉', 'Podcasting': '🎙️',
    'Avatar': '👤', 'Translation': '🌐', 'AI Detection': '🔍',
    'Aggregators': '📦', 'Motion Capture': '🏃', 'Generative Code': '💻',
    'Image Scanning': '📸', 'Generative Video': '📹', 'Voice Modulation': '🎤',
    'Prompt Guides': '📝', 'Speech-To-Text': '📜', 'Inspiration': '💡',
    "Matt's Picks": '⭐',
}

DEFAULT_ICON = '🔧'


def create_sample_data():
    """Seed the database from the CSV file."""
    from models import db, Tool, Category
    
    csv_path = os.path.join(os.path.dirname(__file__), 'futuretools_full_safe_with_tags.csv')
    if not os.path.exists(csv_path):
        print("⚠️  CSV file not found, skipping seed")
        return

    print(f"📄 Seeding database from {os.path.basename(csv_path)}...")

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} tools")

    # Track unique categories
    seen_categories = {}
    tool_count = 0

    for row in rows:
        name = row.get('name', '').strip()
        if not name:
            continue

        # Parse categories (may be comma-separated)
        raw_cats = row.get('categories', '').strip()
        primary_cat = raw_cats.split(',')[0].strip() if raw_cats else 'Uncategorized'

        # Parse tags
        raw_tags = row.get('tags', '').strip()
        tags_list = [t.strip() for t in raw_tags.split(',') if t.strip()] if raw_tags else []

        # Pick an icon based on first matching category
        icon = DEFAULT_ICON
        for cat_part in raw_cats.split(','):
            cat_part = cat_part.strip()
            if cat_part in CATEGORY_ICONS:
                icon = CATEGORY_ICONS[cat_part]
                break

        # Build short description (max 200 chars)
        desc = row.get('description', '').strip() or name
        short_desc = desc[:197] + '...' if len(desc) > 200 else desc

        # Build features from long_description
        long_desc = row.get('long_description', '').strip() or ''
        features = []
        if long_desc:
            # Split into sentences and take up to 5 as features
            sentences = [s.strip() for s in long_desc.replace('. ', '.|').split('|') if s.strip()]
            features = sentences[:5]

        tool = Tool(
            name=name,
            description=long_desc or desc,
            short_description=short_desc,
            logo=icon,
            category=primary_cat,
            rating=round(random.uniform(3.5, 5.0), 1),
            review_count=random.randint(0, 200),
            pricing=row.get('pricing', 'Free').strip() or 'Free',
            website=row.get('website', '').strip() or row.get('external_url', '').strip() or '#',
            features=json.dumps(features),
            integrations=json.dumps([]),
            tags=json.dumps(tags_list),
        )
        db.session.add(tool)
        tool_count += 1

        # Track categories for later
        for cat_part in raw_cats.split(','):
            cat_part = cat_part.strip()
            if cat_part and cat_part not in seen_categories:
                seen_categories[cat_part] = {
                    'icon': CATEGORY_ICONS.get(cat_part, DEFAULT_ICON),
                    'count': 0
                }
            if cat_part:
                seen_categories[cat_part]['count'] = seen_categories.get(cat_part, {}).get('count', 0) + 1

    # Create category records
    for cat_name, cat_info in seen_categories.items():
        cat = Category(
            name=cat_name,
            icon=cat_info['icon'],
            description=f"AI tools for {cat_name.lower()}",
            tool_count=cat_info['count']
        )
        db.session.add(cat)

    db.session.commit()
    print(f"   ✅ Inserted {tool_count} tools and {len(seen_categories)} categories")
