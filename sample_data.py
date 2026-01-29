from models import db, Tool

def create_sample_data():
    """Populate database with sample AI tools"""
    print("🌱 Seeding database with AI tools...")
    
    tools_data = [
        # --- Chatbots & Assistants ---
        {
            "name": "ChatGPT",
            "description": "OpenAI's state-of-the-art conversational AI model capable of answering questions, writing copy, coding, and more. It set the standard for modern LLMs.",
            "short_description": "Advanced conversational AI by OpenAI",
            "logo": "🤖",
            "category": "Chatbots",
            "pricing": "Freemium",
            "website": "https://chat.openai.com",
            "tags": ["chat", "writing", "coding", "assistant"]
        },
        {
            "name": "Claude",
            "description": "Anthropic's AI assistant focused on being helpful, harmless, and honest. Known for its large context window and natural writing style.",
            "short_description": "Constitutional AI assistant by Anthropic",
            "logo": "🧠",
            "category": "Chatbots",
            "pricing": "Freemium",
            "website": "https://claude.ai",
            "tags": ["chat", "writing", "analysis"]
        },
        {
            "name": "Perplexity AI",
            "description": "An AI-powered search engine that provides real-time answers with citations. It searches the web to give you up-to-date information.",
            "short_description": "AI search engine with citations",
            "logo": "🔎",
            "category": "Search",
            "pricing": "Freemium",
            "website": "https://www.perplexity.ai",
            "tags": ["search", "research", "assistant"]
        },
        {
            "name": "Gemini",
            "description": "Google's most capable AI model, integrated into Google's ecosystem. Good for multimodal tasks including text, code, and images.",
            "short_description": "Google's multimodal AI assistant",
            "logo": "💎",
            "category": "Chatbots",
            "pricing": "Freemium",
            "website": "https://gemini.google.com",
            "tags": ["google", "multimodal", "chat"]
        },
        
        # --- Image Generation ---
        {
            "name": "Midjourney",
            "description": "A research lab's AI program that creates stunning, artistic images from textual descriptions. Accessed via Discord.",
            "short_description": "High-quality artistic image generation",
            "logo": "🎨",
            "category": "Image Generation",
            "pricing": "Paid",
            "website": "https://www.midjourney.com",
            "tags": ["art", "images", "discord"]
        },
        {
            "name": "Canva Magic Studio",
            "description": "A suite of AI tools integrated into Canva, allowing for image generation, magic edits, and design automation.",
            "short_description": "AI design tools within Canva",
            "logo": "✨",
            "category": "Design",
            "pricing": "Freemium",
            "website": "https://www.canva.com",
            "tags": ["design", "social media", "images"]
        },
        {
            "name": "Stable Diffusion",
            "description": "An open-source deep learning model that generates detailed images from text descriptions. Can be run locally.",
            "short_description": "Open-source text-to-image model",
            "logo": "🖼️",
            "category": "Image Generation",
            "pricing": "Free",
            "website": "https://stability.ai",
            "tags": ["open-source", "images", "local"]
        },

        # --- Writing & Content ---
        {
            "name": "Jasper",
            "description": "An AI writing assistant built for marketing and business. Helps write blog posts, ad copy, and social media content.",
            "short_description": "AI copywriter for marketing",
            "logo": "✍️",
            "category": "Writing",
            "pricing": "Paid",
            "website": "https://www.jasper.ai",
            "tags": ["marketing", "copywriting", "business"]
        },
        {
            "name": "Grammarly",
            "description": "An automated grammar checker and writing assistant that helps you write mistake-free and clear text.",
            "short_description": "AI grammar and writing assistant",
            "logo": "📝",
            "category": "Writing",
            "pricing": "Freemium",
            "website": "https://www.grammarly.com",
            "tags": ["grammar", "editing", "productivity"]
        },
        {
            "name": "Copy.ai",
            "description": "An AI-powered copywriter that generates high-quality copy for your business, from blog posts to sales emails.",
            "short_description": "Marketing copy generator",
            "logo": "📄",
            "category": "Writing",
            "pricing": "Freemium",
            "website": "https://www.copy.ai",
            "tags": ["copywriting", "marketing", "email"]
        },

        # --- Audio & Video ---
        {
            "name": "ElevenLabs",
            "description": "The most realistic AI voice generator. Create lifelike speech in any language and voice.",
            "short_description": "Realistic AI voice synthesis",
            "logo": "🗣️",
            "category": "Audio",
            "pricing": "Freemium",
            "website": "https://elevenlabs.io",
            "tags": ["voice", "tts", "audio"]
        },
        {
            "name": "Runway",
            "description": "An applied AI research company shaping the next era of art, entertainment and human creativity. Known for Gen-2 video generation.",
            "short_description": "AI video generation and editing",
            "logo": "🎬",
            "category": "Video",
            "pricing": "Freemium",
            "website": "https://runwayml.com",
            "tags": ["video", "editing", "creative"]
        },
        {
            "name": "Suno",
            "description": "Make a song about anything. Suno is building a future where anyone can make great music.",
            "short_description": "AI music generation",
            "logo": "🎵",
            "category": "Audio",
            "pricing": "Freemium",
            "website": "https://suno.com",
            "tags": ["music", "audio", "creative"]
        },

        # --- Coding & Productivity ---
        {
            "name": "GitHub Copilot",
            "description": "Your AI pair programmer. Copilot uses OpenAI Codex to suggest code and entire functions in real-time.",
            "short_description": "AI pair programmer",
            "logo": "💻",
            "category": "Coding",
            "pricing": "Paid",
            "website": "https://github.com/features/copilot",
            "tags": ["coding", "developer", "productivity"]
        },
        {
            "name": "Notion AI",
            "description": "Access the limitless power of AI, right inside Notion. Work faster. Write better. Think bigger.",
            "short_description": "AI integrated into Notion",
            "logo": "📓",
            "category": "Productivity",
            "pricing": "Paid",
            "website": "https://www.notion.so/product/ai",
            "tags": ["productivity", "notes", "writing"]
        },
        {
            "name": "Taskade",
            "description": "Build and deploy AI Agents to automate tasks. The all-in-one AI workspace for teams.",
            "short_description": "AI agents and project management",
            "logo": "✅",
            "category": "Productivity",
            "pricing": "Freemium",
            "website": "https://www.taskade.com",
            "tags": ["productivity", "agents", "tasks"]
        }
    ]

    count = 0
    for tool_data in tools_data:
        # Check if exists
        existing = Tool.query.filter_by(name=tool_data['name']).first()
        if not existing:
            tool = Tool(
                name=tool_data['name'],
                description=tool_data['description'],
                short_description=tool_data['short_description'],
                logo=tool_data['logo'],
                category=tool_data['category'],
                pricing=tool_data['pricing'],
                website=tool_data['website'],
                features='[]',
                tags=str(tool_data.get('tags', []))
            )
            db.session.add(tool)
            count += 1
    
    db.session.commit()
    print(f"✅ Added {count} new tools to the database.")
