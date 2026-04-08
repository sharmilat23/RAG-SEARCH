from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from sqlalchemy import text
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded
from werkzeug.middleware.proxy_fix import ProxyFix
# Flask-Mail will be imported lazily when needed
from models import db, User, Tool, Prompt, Post, Category, ToolBookmark, PromptBookmark, ToolVote, PromptVote, PostVote, FollowedCategory, UserActivity, UserNotification, PromptLike, PostLike, ToolReview, PostComment, CommentLike
import json
import os
import math
from typing import List, Tuple
import time
from pathlib import Path
from datetime import datetime, timedelta
import gc  # For garbage collection
# Lazy: import email libs only when needed
# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Loaded environment variables from .env file")
except ImportError:
    print("💡 Install python-dotenv to load .env files: pip install python-dotenv")
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}")

# Lazy import OAuth - only load when needed
_oauth = None
_google = None
_oauth_initialized = False

# Reuse the same RAG retrieval pipeline as chatbot for relevance search.
def rag_search_tools(query: str, limit: int, category_filter: str = 'All', pricing_filter: str = 'All'):
    """Return tools ranked by the chatbot RAG retriever (Supabase + Gemini)."""
    try:
        from rag_pipeline import retrieve_documents
        docs = retrieve_documents(query, top_k=max(limit * 2, 5))
    except Exception as e:
        print(f"⚠️  RAG retrieval unavailable for /search: {e}")
        return []

    matched_tools = []
    seen_tool_ids = set()

    for doc in docs:
        metadata = doc.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        tool_name = (metadata.get('name') or '').strip()
        if not tool_name:
            continue

        tool = Tool.query.filter(db.func.lower(Tool.name) == tool_name.lower()).first()
        if not tool or tool.id in seen_tool_ids:
            continue

        if category_filter != 'All' and tool.category != category_filter:
            continue
        if pricing_filter != 'All' and tool.pricing != pricing_filter:
            continue

        seen_tool_ids.add(tool.id)
        matched_tools.append(tool)

        if len(matched_tools) >= limit:
            break

    return matched_tools

# Module cache for frequently used imports
_module_cache = {}

def get_cached_module(module_name):
    """Get a cached module, importing if not already cached"""
    if module_name not in _module_cache:
        try:
            _module_cache[module_name] = __import__(module_name)
        except ImportError:
            _module_cache[module_name] = None
    return _module_cache[module_name]

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-insecure-secret-key-change-me')
if app.config['SECRET_KEY'] == 'dev-insecure-secret-key-change-me':
    print("⚠️  SECRET_KEY not set. Using insecure development default.")
# Database configuration - use DATABASE_URL, fallback to SQLite for local dev
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    basedir = os.path.abspath(os.path.dirname(__file__))
    database_url = 'sqlite:///' + os.path.join(basedir, 'app.db')
    print(f"💡 No DATABASE_URL set, using SQLite: {database_url}")
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Rate limiting configuration
# Prefer external storage via env (e.g., Redis); fallback to in-memory
_ratelimit_storage_uri = (
    os.environ.get('RATELIMIT_STORAGE_URI')
    or os.environ.get('REDIS_URL')
    or 'memory://'
)

# Force memory storage for development if Redis is not available
if _ratelimit_storage_uri.startswith('redis://') or _ratelimit_storage_uri.startswith('rediss://'):
    try:
        import redis
        r = redis.from_url(_ratelimit_storage_uri)
        r.ping()  # Test connection
    except:
        print("⚠️  Redis connection failed, falling back to memory storage")
        _ratelimit_storage_uri = 'memory://'

# Configure ProxyFix for Cloudflare
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
)

# Custom key function to get real client IP from Cloudflare
def get_real_ip():
    # Prefer CF-Connecting-IP, fallback to remote_addr
    real_ip = request.headers.get('CF-Connecting-IP', request.remote_addr)
    print(f"DEBUG - Remote Address: {request.remote_addr}")
    print(f"DEBUG - Real IP: {real_ip}")
    print(f"DEBUG - CF-Connecting-IP: {request.headers.get('CF-Connecting-IP', 'None')}")
    print(f"DEBUG - X-Forwarded-For: {request.headers.get('X-Forwarded-For', 'None')}")
    return real_ip

# Initialize limiter with fallback to memory storage
try:
    limiter = Limiter(
        get_real_ip,  # Use our custom function instead of get_remote_address
        app=app,
        storage_uri=_ratelimit_storage_uri,
        default_limits=["60 per minute", "200 per day"]
    )
    print(f"✅ Rate limiting configured with storage: {_ratelimit_storage_uri}")
except Exception as e:
    print(f"⚠️  Rate limiting storage failed, using memory fallback: {e}")
    limiter = Limiter(
        get_real_ip,
        app=app,
        storage_uri='memory://',
        default_limits=["60 per minute", "200 per day"]
    )

# Mail configuration (use environment variables)
app.config['MAIL_SERVER'] = os.environ.get('SMTP_HOST', '')
app.config['MAIL_PORT'] = int(os.environ.get('SMTP_PORT', '587'))
app.config['MAIL_USERNAME'] = os.environ.get('SMTP_USER', '')
app.config['MAIL_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_SENDER', 'no-reply@aitoolshub.local')
app.config['EMAIL_VERIFY_SALT'] = os.environ.get('EMAIL_VERIFY_SALT', 'email-verify-salt')

# Debug: Print database configuration (without password)
if 'postgresql://' in database_url:
    print(f"✅ Using PostgreSQL: {database_url.split('@')[1] if '@' in database_url else 'Unknown host'}")
else:
    print(f"⚠️  Using SQLite database: {database_url}")

# Database connection pooling for better memory management
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 180,  # Reduce to 3 minutes
    'pool_size': 3,       # Reduce pool size
    'max_overflow': 5,    # Reduce overflow
    'pool_timeout': 30,   # Add timeout
    'echo': False,        # Disable SQL logging in production
    'echo_pool': False    # Disable pool logging
}

# Google OAuth Configuration
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'your-google-client-id-here')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'your-google-client-secret-here')

# Performance and SEO optimizations - lazy loaded
_compress = None

def init_compress():
    """Initialize Flask-Compress only when needed"""
    global _compress
    if _compress is None:
        try:
            from flask_compress import Compress
            _compress = Compress(app)
        except ImportError:
            print("⚠️  Flask-Compress not available. Compression disabled.")
            _compress = False
    return _compress

# Initialize compression
init_compress()

# Add security headers and memory cleanup
@app.after_request
def after_request(response):
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Cache control for static assets
    if request.endpoint == 'static':
        response.headers['Cache-Control'] = 'public, max-age=31536000'  # 1 year
    
    # Periodic garbage collection for memory optimization
    if hasattr(gc, 'collect'):
        gc.collect()
    
    return response

# Return standardized JSON for rate limit errors on API routes
@app.errorhandler(RateLimitExceeded)
def handle_rate_limit_exceeded(e):
    # If the request is for an API route, return JSON
    path = request.path or ''
    if path.startswith('/api/'):
        # Check if this is the agent chat endpoint with daily limit
        if path == '/api/agent/chat':
            return jsonify({
                'success': False,
                'message': 'You have ran out of credits try again tomorrow',
                'error': 'rate_limited'
            }), 429
        else:
            return jsonify({
                'success': False,
                'message': 'Too many requests. Please slow down.',
                'error': 'rate_limited'
            }), 429
    # Fallback to default behavior for non-API routes
    return ("Too Many Requests", 429)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize Flask-Mail lazily
_mail = None

def get_mail():
    """Get Flask-Mail instance, initializing if needed"""
    global _mail
    if _mail is None:
        try:
            from flask_mail import Mail
            _mail = Mail(app)
        except ImportError:
            print("⚠️  Flask-Mail not available. Email features disabled.")
            _mail = False
    return _mail

# --- Startup check to ensure new columns exist (SQLite/Postgres) ---
with app.app_context():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        # Quote reserved table name for Postgres
        table_name = '"user"'
        columns = {c['name'] for c in inspector.get_columns('user')}
        needed = {'email_verified', 'email_verification_token', 'email_verified_at'}
        missing = [c for c in needed if c not in columns]
        if missing:
            for col in missing:
                if col == 'email_verified':
                    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"))
                elif col == 'email_verification_token':
                    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN email_verification_token VARCHAR(255) NULL"))
                elif col == 'email_verified_at':
                    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN email_verified_at TIMESTAMP NULL"))
            db.session.commit()
            print(f"✅ Added missing user columns: {', '.join(missing)}")
    except Exception as e:
        print(f"⚠️  Column check failed or not supported: {e}")

# --- Startup check for Tool embedding columns (for semantic search) ---
with app.app_context():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tool_columns = {c['name'] for c in inspector.get_columns('tool')}
        embedding_cols = {'embedding', 'embedding_text'}
        missing_embedding = [c for c in embedding_cols if c not in tool_columns]
        if missing_embedding:
            for col in missing_embedding:
                if col == 'embedding':
                    db.session.execute(text("ALTER TABLE tool ADD COLUMN embedding TEXT NULL"))
                elif col == 'embedding_text':
                    db.session.execute(text("ALTER TABLE tool ADD COLUMN embedding_text TEXT NULL"))
            db.session.commit()
            print(f"✅ Added embedding columns to Tool table: {', '.join(missing_embedding)}")
    except Exception as e:
        print(f"⚠️  Tool embedding column check failed: {e}")

# --- Email verification helpers ---
def _get_serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(app.config['SECRET_KEY'])

def generate_email_verification_token(user: User) -> str:
    serializer = _get_serializer()
    payload = {'user_id': user.id, 'email': user.email}
    token = serializer.dumps(payload, salt=app.config['EMAIL_VERIFY_SALT'])
    return token

def confirm_email_token(token: str, max_age_seconds: int = 60 * 60 * 24) -> dict | None:
    from itsdangerous import BadSignature, SignatureExpired
    serializer = _get_serializer()
    try:
        data = serializer.loads(token, salt=app.config['EMAIL_VERIFY_SALT'], max_age=max_age_seconds)
        return data
    except (BadSignature, SignatureExpired):
        return None

def send_email(to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Send email using Flask-Mail with lazy loading"""
    # If SMTP is not configured, log to console and pretend success (dev mode)
    if not app.config['MAIL_SERVER'] or not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        print(f"[DEV EMAIL] To: {to_email}\nSubject: {subject}\nBody: {text_body or html_body}")
        return True
    
    mail = get_mail()
    if not mail:
        print("⚠️  Flask-Mail not available. Email not sent.")
        return False
    
    try:
        # Use cached import for Message
        flask_mail = get_cached_module('flask_mail')
        if not flask_mail:
            raise ImportError("Flask-Mail not available")
        
        msg = flask_mail.Message(
            subject=subject,
            recipients=[to_email],
            html=html_body,
            body=text_body
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False

def send_verification_email(user: User) -> bool:
    token = generate_email_verification_token(user)
    user.email_verification_token = token
    db.session.commit()
    verify_url = url_for('verify_email', token=token, _external=True)
    subject = f'Verify your email for {"ANY SITE HUB"}'
    text = f"Hi {user.username},\n\nPlease verify your email by clicking the link below:\n{verify_url}\n\nThis link expires in 24 hours."
    html = f"""
    <p>Hi {user.username},</p>
    <p>Please verify your email by clicking the button below:</p>
    <p><a href="{verify_url}" style=\"background:#3b82f6;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none\">Verify Email</a></p>
    <p>Or open this link:<br>{verify_url}</p>
    <p>This link expires in 24 hours.</p>
    """
    return send_email(user.email, subject, html, text)

def generate_password_reset_token(user: User) -> str:
    """Generate a secure password reset token"""
    secrets = get_cached_module('secrets')
    hashlib = get_cached_module('hashlib')
    hmac = get_cached_module('hmac')
    
    if not secrets or not hashlib or not hmac:
        raise ImportError("Required modules for password reset not available")
    
    # Create a unique token with timestamp
    timestamp = str(int(time.time()))
    random_part = secrets.token_urlsafe(32)
    token_data = f"{user.id}:{user.email}:{timestamp}:{random_part}"
    
    # Sign the token with the secret key
    signature = hmac.new(
        app.config['SECRET_KEY'].encode(),
        token_data.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return f"{token_data}:{signature}"

def verify_password_reset_token(token: str) -> dict:
    """Verify and parse a password reset token"""
    try:
        hmac = get_cached_module('hmac')
        hashlib = get_cached_module('hashlib')
        
        if not hmac or not hashlib:
            return None
        
        if not token or ':' not in token:
            return None
            
        parts = token.split(':')
        if len(parts) != 5:  # user_id:email:timestamp:random:signature
            return None
            
        user_id, email, timestamp, random_part, signature = parts
        
        # Recreate the token data
        token_data = f"{user_id}:{email}:{timestamp}:{random_part}"
        
        # Verify signature
        expected_signature = hmac.new(
            app.config['SECRET_KEY'].encode(),
            token_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return None
            
        # Check if token is not too old (24 hours)
        token_time = int(timestamp)
        current_time = int(time.time())
        if current_time - token_time > 24 * 60 * 60:  # 24 hours
            return None
            
        return {
            'user_id': int(user_id),
            'email': email,
            'timestamp': token_time
        }
    except:
        return None

def send_password_reset_email(user: User) -> bool:
    """Send password reset email to user"""
    token = generate_password_reset_token(user)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow().replace(microsecond=0) + timedelta(hours=24)
    db.session.commit()
    
    reset_url = url_for('reset_password', token=token, _external=True)
    subject = f'Reset your password for {"ANY SITE HUB"}'
    text = f"Hi {user.username},\n\nYou requested a password reset. Click the link below to reset your password:\n{reset_url}\n\nThis link expires in 24 hours.\n\nIf you didn't request this, please ignore this email."
    html = f"""
    <p>Hi {user.username},</p>
    <p>You requested a password reset. Click the button below to reset your password:</p>
    <p><a href="{reset_url}" style="background:#3b82f6;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Reset Password</a></p>
    <p>Or open this link:<br>{reset_url}</p>
    <p>This link expires in 24 hours.</p>
    <p>If you didn't request this, please ignore this email.</p>
    """
    return send_email(user.email, subject, html, text)

def init_oauth():
    """Initialize OAuth only when needed with caching"""
    global _oauth, _google, _oauth_initialized
    
    if _oauth_initialized:
        return _oauth, _google
    
    try:
        # Use cached import for OAuth
        authlib = get_cached_module('authlib')
        if not authlib:
            raise ImportError("Authlib not available")
        
        from authlib.integrations.flask_client import OAuth
        _oauth = OAuth(app)
        
        # Check if Google OAuth credentials are configured
        if (app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET'] and 
            app.config['GOOGLE_CLIENT_ID'] != 'your-google-client-id-here' and 
            app.config['GOOGLE_CLIENT_SECRET'] != 'your-google-client-secret-here'):
            
            _google = _oauth.register(
                name='google',
                client_id=app.config['GOOGLE_CLIENT_ID'],
                client_secret=app.config['GOOGLE_CLIENT_SECRET'],
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                client_kwargs={
                    'scope': 'openid email profile'
                }
            )
            print("✅ Google OAuth configured successfully")
        else:
            print("⚠️  Google OAuth not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.")
            _google = None
    except ImportError:
        print("⚠️  Authlib not available. OAuth features disabled.")
        _oauth = None
        _google = None
    except Exception as e:
        print(f"⚠️  OAuth initialization failed: {e}")
        _oauth = None
        _google = None
    
    _oauth_initialized = True
    return _oauth, _google

def get_oauth():
    """Get OAuth instance, initializing if needed"""
    oauth, google = init_oauth()
    return oauth

def get_google():
    """Get Google OAuth instance, initializing if needed"""
    oauth, google = init_oauth()
    return google

# Helper functions for user actions
def record_activity(user_id, activity_type, points_earned, description):
    """Record user activity and award points"""
    activity = UserActivity(
        user_id=user_id,
        activity_type=activity_type,
        points_earned=points_earned,
        description=description
    )
    db.session.add(activity)
    
    # Update user points
    user = db.session.get(User, user_id)
    if user:
        user.add_points(points_earned)
    
    db.session.commit()

def create_notification(user_id, notification_type, title, message):
    """Create a notification for a user"""
    notification = UserNotification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message
    )
    db.session.add(notification)
    db.session.commit()

def check_badge_conditions(user):
    """Check if user qualifies for new badges"""
    badges = user.get_badges()
    
    # First contribution badge
    if 'First Contribution' not in badges and user.activities:
        user.add_badge('First Contribution')
        create_notification(user.id, 'badge', 'New Badge: First Contribution', 
                          'Congratulations! You\'ve earned your first contribution badge.')
    
    # Top contributor badge (10+ contributions)
    contributions = len([a for a in user.activities if 'contribution' in a.activity_type])
    if 'Top Contributor' not in badges and contributions >= 10:
        user.add_badge('Top Contributor')
        create_notification(user.id, 'badge', 'New Badge: Top Contributor', 
                          'You\'ve become a top contributor with 10+ contributions!')
    
    # Quality master badge (50+ upvotes received)
    total_upvotes = sum([a.points_earned for a in user.activities if 'upvote' in a.activity_type])
    if 'Quality Master' not in badges and total_upvotes >= 50:
        user.add_badge('Quality Master')
        create_notification(user.id, 'badge', 'New Badge: Quality Master', 
                          'Your content quality is exceptional! You\'ve earned the Quality Master badge.')
    
    db.session.commit()

# Custom Jinja filters
@app.template_filter('from_json')
def from_json(value):
    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if result else []
        except:
            return []
    return value if value else []

from urllib.parse import urlparse

@app.template_filter('domain_from_url')
def domain_from_url(url):
    try:
        d = urlparse(url).netloc or (url or '')
        if d.startswith('www.'):
            d = d[4:]
        return d
    except Exception:
        return (url or '')

@app.template_filter('format_number')
def format_number(value):
    if value is None:
        return '0'
    try:
        return f"{int(value):,}"
    except:
        return str(value)

@app.template_filter('safe_slice')
def safe_slice(value, start, end=None):
    if not value:
        return []
    try:
        if end is None:
            return value[start:]
        return value[start:end]
    except:
        return []

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# SEO Routes
@app.context_processor
def inject_seo_constants():
    """Inject global SEO/brand constants into all templates."""
    return {
        'SITE_NAME': 'ANY SITE HUB',
        'BRAND_ALIASES': ['AI TOOLS HUB', 'STERO SONIC LABS'],
        'DEFAULT_SEO_KEYWORDS': 'ANY SITE HUB, AI TOOLS HUB, STERO SONIC LABS, AI tools, artificial intelligence, AI prompts, productivity tools, automation tools, machine learning tools, image generation, AI writing, AI community'
    }

@app.route('/robots.txt')
def robots_txt():
    """Dynamically generate robots.txt with correct sitemap URL."""
    lines = [
        'User-agent: *',
        'Allow: /',
        '',
        '# Sitemap',
        f'Sitemap: {request.url_root.rstrip("/")}/sitemap.xml',
        '',
        '# Disallow admin and private areas',
        'Disallow: /admin/',
        'Disallow: /api/',
        'Disallow: /dashboard/',
        'Disallow: /login/',
        'Disallow: /register/',
        '',
        '# Allow important pages',
        'Allow: /categories/',
        'Allow: /search/',
        'Allow: /prompts/',
        'Allow: /community/',
        'Allow: /tool/',
        'Allow: /prompt/',
        'Allow: /post/',
        '',
        '# Crawl delay (optional)',
        'Crawl-delay: 1',
    ]
    content = "\n".join(lines)
    return app.response_class(response=content, status=200, mimetype='text/plain')

# Favicon routes - serve actual favicon files
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico', mimetype='image/vnd.microsoft.icon'
    )

@app.route('/favicon-16x16.png')
def favicon_16():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon-16x16.png', mimetype='image/png'
    )

@app.route('/favicon-32x32.png')
def favicon_32():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon-32x32.png', mimetype='image/png'
    )

@app.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'apple-touch-icon.png', mimetype='image/png'
    )

# Android Chrome icons for PWA
@app.route('/android-chrome-192x192.png')
def android_chrome_192():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'android-chrome-192x192.png', mimetype='image/png'
    )

@app.route('/android-chrome-512x512.png')
def android_chrome_512():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'android-chrome-512x512.png', mimetype='image/png'
    )

# Additional favicon formats
@app.route('/favicon.svg')
def favicon_svg():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.svg', mimetype='image/svg+xml'
    )

@app.route('/logo.svg')
def logo_svg():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'logo.svg', mimetype='image/svg+xml'
    )

@app.route('/sitemap.xml')
def sitemap():
    """Generate XML sitemap for search engines"""
    try:
        # Get limited tools (most recent/popular)
        tools = Tool.query.order_by(Tool.review_count.desc(), Tool.rating.desc()).limit(1000).all()
        # Get limited prompts (most recent/popular)
        prompts = Prompt.query.order_by(Prompt.upvotes.desc(), Prompt.created_at.desc()).limit(1000).all()
        # Get limited posts (most recent/popular)
        posts = Post.query.order_by(Post.upvotes.desc(), Post.created_at.desc()).limit(1000).all()
        
        # Generate sitemap XML
        sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        
        # Homepage
        sitemap_xml += '  <url>\n'
        sitemap_xml += f'    <loc>{request.url_root}</loc>\n'
        sitemap_xml += '    <lastmod>' + datetime.utcnow().strftime('%Y-%m-%d') + '</lastmod>\n'
        sitemap_xml += '    <changefreq>daily</changefreq>\n'
        sitemap_xml += '    <priority>1.0</priority>\n'
        sitemap_xml += '  </url>\n'
        
        # Main pages
        main_pages = [
            ('categories', 0.9, 'weekly'),
            ('search', 0.8, 'weekly'),
            ('prompts', 0.8, 'weekly'),
            ('community', 0.8, 'weekly'),
            ('ai_agent', 0.7, 'monthly')
        ]
        
        for page, priority, changefreq in main_pages:
            sitemap_xml += '  <url>\n'
            sitemap_xml += f'    <loc>{request.url_root}{page}</loc>\n'
            sitemap_xml += '    <lastmod>' + datetime.utcnow().strftime('%Y-%m-%d') + '</lastmod>\n'
            sitemap_xml += f'    <changefreq>{changefreq}</changefreq>\n'
            sitemap_xml += f'    <priority>{priority}</priority>\n'
            sitemap_xml += '  </url>\n'
        
        # Tool pages
        for tool in tools:
            sitemap_xml += '  <url>\n'
            sitemap_xml += f'    <loc>{request.url_root}tool/{tool.id}</loc>\n'
            sitemap_xml += '    <lastmod>' + datetime.utcnow().strftime('%Y-%m-%d') + '</lastmod>\n'
            sitemap_xml += '    <changefreq>weekly</changefreq>\n'
            sitemap_xml += '    <priority>0.8</priority>\n'
            sitemap_xml += '  </url>\n'
        
        # Prompt pages
        for prompt in prompts:
            sitemap_xml += '  <url>\n'
            sitemap_xml += f'    <loc>{request.url_root}prompt/{prompt.id}</loc>\n'
            sitemap_xml += '    <lastmod>' + prompt.created_at.strftime('%Y-%m-%d') + '</lastmod>\n'
            sitemap_xml += '    <changefreq>monthly</changefreq>\n'
            sitemap_xml += '    <priority>0.7</priority>\n'
            sitemap_xml += '  </url>\n'
        
        # Post pages
        for post in posts:
            sitemap_xml += '  <url>\n'
            sitemap_xml += f'    <loc>{request.url_root}post/{post.id}</loc>\n'
            sitemap_xml += '    <lastmod>' + post.created_at.strftime('%Y-%m-%d') + '</lastmod>\n'
            sitemap_xml += '    <changefreq>monthly</changefreq>\n'
            sitemap_xml += '    <priority>0.6</priority>\n'
            sitemap_xml += '  </url>\n'
        
        sitemap_xml += '</urlset>'
        
        response = app.response_class(
            response=sitemap_xml,
            status=200,
            mimetype='application/xml'
        )
        return response
        
    except Exception as e:
        return f"Error generating sitemap: {str(e)}", 500

# Routes
@app.route('/')
def home():
    try:
        # Trending tools: recent reviews and rating weight, fallback to rating/review_count
        tools = Tool.query.order_by(Tool.review_count.desc(), Tool.rating.desc()).limit(6).all()

        # Trending prompts by likes then upvotes
        prompts = Prompt.query.order_by(Prompt.likes.desc(), (Prompt.upvotes - Prompt.downvotes).desc()).limit(3).all()

        # Trending posts by likes then upvotes/comments
        posts = Post.query.order_by(Post.likes.desc(), Post.upvotes.desc(), Post.comments.desc()).limit(3).all()

        # Build categories from Tool.category with counts for the home page (limit to top categories)
        category_rows = db.session.query(
            Tool.category, db.func.count(Tool.id)
        ).group_by(Tool.category).order_by(db.func.count(Tool.id).desc()).limit(10).all()

        # Simple default icon map; fallback to a generic icon
        default_icons = {
            'Writing': '📝',
            'Design': '🎨',
            'Coding': '💻',
            'Marketing': '📣',
            'Research': '🔎'
        }
        categories = [
            {
                'name': row[0],
                'tool_count': row[1],
                'icon': default_icons.get(row[0], '🧰')
            }
            for row in category_rows if row[0]
        ]

        return render_template('home.html', tools=tools, prompts=prompts, posts=posts, categories=categories)
    except Exception as e:
        # If there's an error, return empty lists
        return render_template('home.html', tools=[], prompts=[], posts=[], categories=[])

@app.route('/categories')
def categories():
    try:
        search = request.args.get('search', '')
        category_filter = request.args.get('category', 'All')
        pricing_filter = request.args.get('pricing', 'All')
        sort_by = request.args.get('sort', 'popularity')
        page = request.args.get('page', 1, type=int)
        per_page = 12
        
        tools = Tool.query
        
        # Apply advanced search filter
        if search:
            search_terms = search.split()
            search_conditions = []
            
            for term in search_terms:
                term_condition = (
                    Tool.name.ilike(f'%{term}%') |
                    Tool.description.ilike(f'%{term}%') |
                    Tool.short_description.ilike(f'%{term}%') |
                    Tool.category.ilike(f'%{term}%') |
                    Tool.features.ilike(f'%{term}%') |
                    Tool.tags.ilike(f'%{term}%')
                )
                search_conditions.append(term_condition)
            
            # Combine all search terms with AND logic
            if search_conditions:
                tools = tools.filter(db.and_(*search_conditions))
        
        # Apply filters
        if category_filter != 'All':
            tools = tools.filter(Tool.category == category_filter)
        if pricing_filter != 'All':
            tools = tools.filter(Tool.pricing == pricing_filter)
        
        # Apply sorting with ranking
        if sort_by == 'popularity':
            tools = tools.order_by(Tool.review_count.desc(), Tool.rating.desc())
        elif sort_by == 'rating':
            tools = tools.order_by(Tool.rating.desc(), Tool.review_count.desc())
        elif sort_by == 'name':
            tools = tools.order_by(Tool.name.asc())
        elif sort_by == 'newest':
            tools = tools.order_by(Tool.id.desc())
        elif sort_by == 'relevance' and search:
            # Custom relevance scoring for search results
            tools = tools.order_by(
                db.case(
                    (Tool.name.ilike(f'%{search}%'), 100),
                    (Tool.short_description.ilike(f'%{search}%'), 80),
                    (Tool.description.ilike(f'%{search}%'), 60),
                    (Tool.category.ilike(f'%{search}%'), 40),
                    else_=20
                ).desc(),
                Tool.rating.desc()
            )
        
        # Pagination
        pagination = tools.paginate(page=page, per_page=per_page, error_out=False)
        tools = pagination.items
        
        # Build categories list from Tool.category for the dropdown
        category_names = db.session.query(Tool.category).distinct().all()
        categories = [{'name': c[0]} for c in category_names if c[0]]
        
        return render_template('categories.html', 
                             tools=tools, 
                             categories=categories, 
                             search=search, 
                             selected_category=category_filter, 
                             selected_pricing=pricing_filter, 
                             sort_by=sort_by,
                             pagination=pagination)
    except Exception as e:
        return render_template('categories.html', tools=[], categories=[], 
                             search='', selected_category='All', selected_pricing='All', sort_by='popularity')

# Reviews API
@app.route('/api/tool/<int:tool_id>/reviews', methods=['GET', 'POST'])
def tool_reviews(tool_id):
    tool = Tool.query.get_or_404(tool_id)

    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'message': 'Login required'}), 401

        data = request.get_json() or {}
        rating = int(data.get('rating', 0))
        content = (data.get('content') or '').strip()

        if rating < 1 or rating > 5:
            return jsonify({'success': False, 'message': 'Rating must be 1-5'}), 400

        # Upsert user's review for the tool
        review = ToolReview.query.filter_by(user_id=current_user.id, tool_id=tool_id).first()
        if review:
            review.rating = rating
            review.content = content
        else:
            review = ToolReview(user_id=current_user.id, tool_id=tool_id, rating=rating, content=content)
            db.session.add(review)

        # Recalculate tool rating and review count
        db.session.flush()
        stats = db.session.query(db.func.count(ToolReview.id), db.func.avg(ToolReview.rating)).filter_by(tool_id=tool_id).first()
        tool.review_count = int(stats[0] or 0)
        tool.rating = float(stats[1] or 0.0)

        # Award activity points
        if review:
            record_activity(current_user.id, 'review_tool', 3, f'Reviewed {tool.name}')
            check_badge_conditions(current_user)

        db.session.commit()
        return jsonify({'success': True, 'message': 'Review saved', 'rating': tool.rating, 'review_count': tool.review_count})

    # GET
    reviews = ToolReview.query.filter_by(tool_id=tool_id).order_by(ToolReview.created_at.desc()).all()
    return jsonify([
        {
            'id': r.id,
            'user': r.user.username,
            'rating': r.rating,
            'content': r.content,
            'created_at': r.created_at.isoformat()
        } for r in reviews
    ])

# Post comments API
@app.route('/api/post/<int:post_id>/comments', methods=['GET', 'POST'])
def post_comments(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'message': 'Login required'}), 401
        data = request.get_json() or {}
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'success': False, 'message': 'Comment cannot be empty'}), 400

        comment = PostComment(post_id=post_id, user_id=current_user.id, content=content)
        db.session.add(comment)
        # Update post comments count
        post.comments = (post.comments or 0) + 1
        db.session.commit()
        return jsonify({'success': True, 'message': 'Comment added', 'comments': post.comments})

    # GET
    comments = PostComment.query.filter_by(post_id=post_id).order_by(PostComment.created_at.asc()).all()
    return jsonify([
        {
            'id': c.id,
            'user': c.user.username,
            'content': c.content,
            'created_at': c.created_at.isoformat()
        } for c in comments
    ])

@app.route('/search')
def search():
    """Dedicated search page with advanced functionality"""
    try:
        query = request.args.get('q', '')
        search_type = request.args.get('type', 'all')  # tools, prompts, posts, all
        category_filter = request.args.get('category', 'All')
        pricing_filter = request.args.get('pricing', 'All')
        sort_by = request.args.get('sort', 'relevance')
        page = request.args.get('page', 1, type=int)
        per_page = 12
        
        results = {
            'tools': [],
            'prompts': [],
            'posts': [],
            'total_results': 0
        }
        
        if query:
            # Search tools
            if search_type in ['tools', 'all']:
                if sort_by == 'relevance':
                    tools_list = rag_search_tools(
                        query=query,
                        limit=per_page,
                        category_filter=category_filter,
                        pricing_filter=pricing_filter
                    )
                    if tools_list:
                        results['tools'] = tools_list
                    else:
                        print("DEBUG: RAG relevance search returned 0 tools in /search, using keyword fallback")

                if sort_by != 'relevance' or not results['tools']:
                    # Fallback to keyword search for non-relevance sorting or if semantic unavailable
                    tools_query = Tool.query
                    
                    # Apply search filter
                    search_terms = query.split()
                    search_conditions = []
                    
                    for term in search_terms:
                        term_condition = (
                            Tool.name.ilike(f'%{term}%') |
                            Tool.description.ilike(f'%{term}%') |
                            Tool.short_description.ilike(f'%{term}%') |
                            Tool.category.ilike(f'%{term}%') |
                            Tool.features.ilike(f'%{term}%') |
                            Tool.tags.ilike(f'%{term}%')
                        )
                        search_conditions.append(term_condition)
                    
                    if search_conditions:
                        tools_query = tools_query.filter(db.and_(*search_conditions))
                    
                    # Apply filters
                    if category_filter != 'All':
                        tools_query = tools_query.filter(Tool.category == category_filter)
                    if pricing_filter != 'All':
                        tools_query = tools_query.filter(Tool.pricing == pricing_filter)
                    
                    # Apply sorting
                    if sort_by == 'relevance':
                        tools_query = tools_query.order_by(
                            db.case(
                                (Tool.name.ilike(f'%{query}%'), 100),
                                (Tool.short_description.ilike(f'%{query}%'), 80),
                                (Tool.description.ilike(f'%{query}%'), 60),
                                (Tool.category.ilike(f'%{query}%'), 40),
                                else_=20
                            ).desc(),
                            Tool.rating.desc()
                        )
                    elif sort_by == 'popularity':
                        tools_query = tools_query.order_by(Tool.review_count.desc(), Tool.rating.desc())
                    elif sort_by == 'rating':
                        tools_query = tools_query.order_by(Tool.rating.desc(), Tool.review_count.desc())
                    elif sort_by == 'name':
                        tools_query = tools_query.order_by(Tool.name.asc())
                    
                    results['tools'] = tools_query.limit(per_page).all()
            
            # Search prompts
            if search_type in ['prompts', 'all']:
                prompts_query = Prompt.query
                
                search_terms = query.split()
                search_conditions = []
                
                for term in search_terms:
                    term_condition = (
                        Prompt.title.ilike(f'%{term}%') |
                        Prompt.content.ilike(f'%{term}%') |
                        Prompt.tool.ilike(f'%{term}%') |
                        Prompt.category.ilike(f'%{term}%') |
                        Prompt.tags.ilike(f'%{term}%')
                    )
                    search_conditions.append(term_condition)
                
                if search_conditions:
                    prompts_query = prompts_query.filter(db.and_(*search_conditions))
                
                if sort_by == 'relevance':
                    prompts_query = prompts_query.order_by(
                        db.case(
                            (Prompt.title.ilike(f'%{query}%'), 100),
                            (Prompt.content.ilike(f'%{query}%'), 80),
                            (Prompt.tool.ilike(f'%{query}%'), 60),
                            (Prompt.category.ilike(f'%{query}%'), 40),
                            else_=20
                        ).desc(),
                        Prompt.upvotes.desc()
                    )
                elif sort_by == 'popularity':
                    prompts_query = prompts_query.order_by(Prompt.upvotes.desc())
                elif sort_by == 'newest':
                    prompts_query = prompts_query.order_by(Prompt.created_at.desc())
                
                results['prompts'] = prompts_query.limit(per_page).all()
            
            # Search posts
            if search_type in ['posts', 'all']:
                posts_query = Post.query
                
                search_terms = query.split()
                search_conditions = []
                
                for term in search_terms:
                    term_condition = (
                        Post.title.ilike(f'%{term}%') |
                        Post.content.ilike(f'%{term}%') |
                        Post.tags.ilike(f'%{term}%')
                    )
                    search_conditions.append(term_condition)
                
                if search_conditions:
                    posts_query = posts_query.filter(db.and_(*search_conditions))
                
                if sort_by == 'relevance':
                    posts_query = posts_query.order_by(
                        db.case(
                            (Post.title.ilike(f'%{query}%'), 100),
                            (Post.content.ilike(f'%{query}%'), 80),
                            else_=20
                        ).desc(),
                        Post.upvotes.desc()
                    )
                elif sort_by == 'popularity':
                    posts_query = posts_query.order_by(Post.upvotes.desc())
                elif sort_by == 'newest':
                    posts_query = posts_query.order_by(Post.created_at.desc())
                
                results['posts'] = posts_query.limit(per_page).all()
            
            # Calculate total results
            results['total_results'] = len(results['tools']) + len(results['prompts']) + len(results['posts'])
        
        # Get categories efficiently from Tool.category field instead of Category table
        category_names = db.session.query(Tool.category).distinct().all()
        categories = [{'name': c[0], 'icon': '🔧', 'description': f'{c[0]} tools', 'tool_count': 0} 
                     for c in category_names if c[0]]
        
        return render_template('search.html', 
                             query=query,
                             search_type=search_type,
                             results=results,
                             categories=categories,
                             category_filter=category_filter,
                             pricing_filter=pricing_filter,
                             sort_by=sort_by)
    except Exception as e:
        return render_template('search.html', 
                             query='',
                             search_type='all',
                             results={'tools': [], 'prompts': [], 'posts': [], 'total_results': 0},
                             categories=[],
                             category_filter='All',
                             pricing_filter='All',
                             sort_by='relevance')

@app.route('/api/search')
def api_search():
    """API endpoint for search functionality"""
    try:
        query = request.args.get('q', '')
        search_type = request.args.get('type', 'all')
        category_filter = request.args.get('category', 'All')
        pricing_filter = request.args.get('pricing', 'All')
        sort_by = request.args.get('sort', 'relevance')
        limit = request.args.get('limit', 10, type=int)
        
        results = []
        
        if query:
            if search_type == 'tools':
                if sort_by == 'relevance':
                    tools = rag_search_tools(
                        query=query,
                        limit=limit,
                        category_filter=category_filter,
                        pricing_filter=pricing_filter
                    )
                else:
                    tools_query = Tool.query

                    # Apply search filter
                    search_terms = query.split()
                    search_conditions = []

                    for term in search_terms:
                        term_condition = (
                            Tool.name.ilike(f'%{term}%') |
                            Tool.description.ilike(f'%{term}%') |
                            Tool.short_description.ilike(f'%{term}%') |
                            Tool.category.ilike(f'%{term}%') |
                            Tool.features.ilike(f'%{term}%') |
                            Tool.tags.ilike(f'%{term}%')
                        )
                        search_conditions.append(term_condition)

                    if search_conditions:
                        tools_query = tools_query.filter(db.and_(*search_conditions))

                    # Apply filters
                    if category_filter != 'All':
                        tools_query = tools_query.filter(Tool.category == category_filter)
                    if pricing_filter != 'All':
                        tools_query = tools_query.filter(Tool.pricing == pricing_filter)

                    # Apply sorting for non-relevance modes
                    if sort_by == 'popularity':
                        tools_query = tools_query.order_by(Tool.review_count.desc(), Tool.rating.desc())
                    elif sort_by == 'rating':
                        tools_query = tools_query.order_by(Tool.rating.desc(), Tool.review_count.desc())
                    elif sort_by == 'name':
                        tools_query = tools_query.order_by(Tool.name.asc())

                    tools = tools_query.limit(limit).all()
                
                for tool in tools:
                    # Calculate relevance score
                    relevance_score = 0
                    if query.lower() in tool.name.lower():
                        relevance_score += 100
                    if query.lower() in tool.short_description.lower():
                        relevance_score += 80
                    if query.lower() in tool.description.lower():
                        relevance_score += 60
                    if query.lower() in tool.category.lower():
                        relevance_score += 40
                    
                    results.append({
                        'id': tool.id,
                        'name': tool.name,
                        'description': tool.short_description,
                        'logo': tool.logo,
                        'category': tool.category,
                        'pricing': tool.pricing,
                        'rating': tool.rating,
                        'review_count': tool.review_count,
                        'relevance_score': relevance_score,
                        'type': 'tool'
                    })
            
            elif search_type == 'prompts':
                prompts_query = Prompt.query
                
                search_terms = query.split()
                search_conditions = []
                
                for term in search_terms:
                    term_condition = (
                        Prompt.title.ilike(f'%{term}%') |
                        Prompt.content.ilike(f'%{term}%') |
                        Prompt.tool.ilike(f'%{term}%') |
                        Prompt.category.ilike(f'%{term}%') |
                        Prompt.tags.ilike(f'%{term}%')
                    )
                    search_conditions.append(term_condition)
                
                if search_conditions:
                    prompts_query = prompts_query.filter(db.and_(*search_conditions))
                
                if sort_by == 'relevance':
                    prompts_query = prompts_query.order_by(
                        db.case(
                            (Prompt.title.ilike(f'%{query}%'), 100),
                            (Prompt.content.ilike(f'%{query}%'), 80),
                            (Prompt.tool.ilike(f'%{query}%'), 60),
                            (Prompt.category.ilike(f'%{query}%'), 40),
                            else_=20
                        ).desc(),
                        Prompt.upvotes.desc()
                    )
                elif sort_by == 'popularity':
                    prompts_query = prompts_query.order_by(Prompt.upvotes.desc())
                elif sort_by == 'newest':
                    prompts_query = prompts_query.order_by(Prompt.created_at.desc())
                
                prompts = prompts_query.limit(limit).all()
                
                for prompt in prompts:
                    relevance_score = 0
                    if query.lower() in prompt.title.lower():
                        relevance_score += 100
                    if query.lower() in prompt.content.lower():
                        relevance_score += 80
                    if query.lower() in prompt.tool.lower():
                        relevance_score += 60
                    if query.lower() in prompt.category.lower():
                        relevance_score += 40
                    
                    results.append({
                        'id': prompt.id,
                        'title': prompt.title,
                        'content': prompt.content[:200] + '...' if len(prompt.content) > 200 else prompt.content,
                        'tool': prompt.tool,
                        'category': prompt.category,
                        'upvotes': prompt.upvotes,
                        'author': prompt.author.username,
                        'relevance_score': relevance_score,
                        'type': 'prompt'
                    })
        
        # Sort by relevance score if not already sorted
        if sort_by == 'relevance':
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return jsonify({
            'success': True,
            'query': query,
            'results': results,
            'total_results': len(results)
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'results': [],
            'total_results': 0
        }), 500

@app.route('/api/search/suggestions')
def search_suggestions():
    """Get search suggestions for autocomplete"""
    try:
        query = request.args.get('q', '').lower()
        limit = request.args.get('limit', 8, type=int)
        
        suggestions = []
        
        if query:
            # Search in tools
            tools = Tool.query.filter(
                (Tool.name.ilike(f'%{query}%')) |
                (Tool.short_description.ilike(f'%{query}%')) |
                (Tool.category.ilike(f'%{query}%'))
            ).limit(limit // 2).all()
            
            for tool in tools:
                suggestions.append(f"{tool.name} - {tool.category}")
            
            # Search in prompts
            prompts = Prompt.query.filter(
                (Prompt.title.ilike(f'%{query}%')) |
                (Prompt.tool.ilike(f'%{query}%')) |
                (Prompt.category.ilike(f'%{query}%'))
            ).limit(limit // 2).all()
            
            for prompt in prompts:
                suggestions.append(f"{prompt.title} - {prompt.tool} prompt")
            
            # If no database results, fall back to static suggestions
            if not suggestions:
                static_suggestions = [
                    'ChatGPT - AI writing assistant',
                    'Midjourney - AI image generation',
                    'GitHub Copilot - AI coding assistant',
                    'Copy.ai - AI copywriting tool',
                    'Notion AI - AI productivity assistant',
                    'Perplexity AI - AI search engine',
                    'Stable Diffusion - AI image generation',
                    'Jasper - AI content creation'
                ]
                suggestions = [s for s in static_suggestions if query in s.lower()]
        
        return jsonify(suggestions[:limit])
    
    except Exception as e:
        return jsonify([])

@app.route('/api/search/advanced')
def advanced_search():
    """Advanced search with multiple filters and faceted search"""
    try:
        query = request.args.get('q', '')
        search_type = request.args.get('type', 'all')
        categories = request.args.getlist('categories[]')
        pricing_options = request.args.getlist('pricing[]')
        rating_min = request.args.get('rating_min', 0, type=float)
        rating_max = request.args.get('rating_max', 5, type=float)
        sort_by = request.args.get('sort', 'relevance')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        results = {
            'tools': [],
            'prompts': [],
            'posts': [],
            'facets': {
                'categories': {},
                'pricing': {},
                'rating_ranges': {}
            },
            'total_results': 0
        }
        
        if query or categories or pricing_options:
            # Search tools
            if search_type in ['tools', 'all']:
                tools_query = Tool.query
                
                # Apply text search
                if query:
                    search_terms = query.split()
                    search_conditions = []
                    
                    for term in search_terms:
                        term_condition = (
                            Tool.name.ilike(f'%{term}%') |
                            Tool.description.ilike(f'%{term}%') |
                            Tool.short_description.ilike(f'%{term}%') |
                            Tool.category.ilike(f'%{term}%') |
                            Tool.features.ilike(f'%{term}%') |
                            Tool.tags.ilike(f'%{term}%')
                        )
                        search_conditions.append(term_condition)
                    
                    if search_conditions:
                        tools_query = tools_query.filter(db.and_(*search_conditions))
                
                # Apply filters
                if categories:
                    tools_query = tools_query.filter(Tool.category.in_(categories))
                if pricing_options:
                    tools_query = tools_query.filter(Tool.pricing.in_(pricing_options))
                if rating_min > 0:
                    tools_query = tools_query.filter(Tool.rating >= rating_min)
                if rating_max < 5:
                    tools_query = tools_query.filter(Tool.rating <= rating_max)
                
                # Apply sorting
                if sort_by == 'relevance' and query:
                    tools_query = tools_query.order_by(
                        db.case(
                            (Tool.name.ilike(f'%{query}%'), 100),
                            (Tool.short_description.ilike(f'%{query}%'), 80),
                            (Tool.description.ilike(f'%{query}%'), 60),
                            (Tool.category.ilike(f'%{query}%'), 40),
                            else_=20
                        ).desc(),
                        Tool.rating.desc()
                    )
                elif sort_by == 'popularity':
                    tools_query = tools_query.order_by(Tool.review_count.desc(), Tool.rating.desc())
                elif sort_by == 'rating':
                    tools_query = tools_query.order_by(Tool.rating.desc(), Tool.review_count.desc())
                elif sort_by == 'name':
                    tools_query = tools_query.order_by(Tool.name.asc())
                elif sort_by == 'newest':
                    tools_query = tools_query.order_by(Tool.id.desc())
                
                # Pagination
                pagination = tools_query.paginate(page=page, per_page=per_page, error_out=False)
                results['tools'] = pagination.items
                
                # Calculate facets using database aggregation (memory efficient)
                # Category facets
                category_counts = db.session.query(
                    Tool.category, db.func.count(Tool.id)
                ).group_by(Tool.category).all()
                results['facets']['categories'] = {cat: count for cat, count in category_counts if cat}
                
                # Pricing facets
                pricing_counts = db.session.query(
                    Tool.pricing, db.func.count(Tool.id)
                ).group_by(Tool.pricing).all()
                results['facets']['pricing'] = {pricing: count for pricing, count in pricing_counts if pricing}
                
                # Rating range facets
                rating_ranges = db.session.query(
                    db.func.floor(Tool.rating).label('rating_floor'),
                    db.func.count(Tool.id)
                ).group_by(db.func.floor(Tool.rating)).all()
                results['facets']['rating_ranges'] = {
                    f"{int(rating_floor)}-{int(rating_floor) + 1}": count 
                    for rating_floor, count in rating_ranges
                }
        
        results['total_results'] = len(results['tools']) + len(results['prompts']) + len(results['posts'])
        
        return jsonify({
            'success': True,
            'results': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total if 'pagination' in locals() else 0,
                'pages': pagination.pages if 'pagination' in locals() else 0
            }
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'results': {'tools': [], 'prompts': [], 'posts': [], 'facets': {}, 'total_results': 0}
        }), 500

@app.route('/tool/<int:tool_id>')
def tool_detail(tool_id):
    tool = Tool.query.get_or_404(tool_id)
    # Find similar tools: prioritize same category, then tag overlap, exclude current tool
    similar = Tool.query.filter(
        Tool.id != tool.id,
        Tool.category == tool.category
    ).order_by(Tool.review_count.desc(), Tool.rating.desc()).limit(6).all()

    # Fallback by tag overlap if needed
    if len(similar) < 3:
        try:
            tag_list = []
            try:
                tag_list = json.loads(tool.tags) if tool.tags else []
            except Exception:
                tag_list = []
            q = Tool.query.filter(Tool.id != tool.id)
            if tag_list:
                like_filters = [Tool.tags.ilike(f'%{t}%') for t in tag_list]
                q = q.filter(db.or_(*like_filters))
            similar_extra = q.order_by(Tool.review_count.desc(), Tool.rating.desc()).limit(6).all()
            # merge unique
            existing_ids = {t.id for t in similar}
            for t in similar_extra:
                if t.id not in existing_ids:
                    similar.append(t)
                if len(similar) >= 6:
                    break
        except Exception:
            pass

    similar_tools = similar[:3]
    return render_template('tool_detail.html', tool=tool, similar_tools=similar_tools)

@app.route('/prompt/<int:prompt_id>')
def prompt_detail(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    return render_template('prompt_detail.html', prompt=prompt)

@app.route('/agent')
@login_required
def ai_agent():
    return render_template('ai_agent.html')

@app.route('/api/agent/chat', methods=['POST'])
@login_required
@limiter.limit("10 per day", key_func=lambda: str(current_user.id) if current_user.is_authenticated else get_remote_address())
@limiter.limit("10 per minute")
def agent_chat():
    """
    AI Agent chat endpoint — powered by the RAG pipeline.
    Replicates the n8n workflow: Gemini embeddings → Supabase retrieval → Mistral LLM.
    """
    data = request.get_json() or {}
    user_input = (data.get('message') or '').strip()
    if not user_input:
        return jsonify({'response': 'Please provide a query.', 'tools': []})

    # Session ID: use user ID for persistent per-user conversation memory
    session_id = f"user_{current_user.id}"

    try:
        from rag_pipeline import generate_response
        response_text = generate_response(user_input, session_id)
    except Exception as e:
        print(f"❌ RAG pipeline error: {e}")
        import traceback
        traceback.print_exc()
        response_text = "I'm sorry, I encountered an error while processing your request. Please try again."

    return jsonify({
        'response': response_text,
        'tools': []  # Kept for frontend backward compatibility
    })


@app.route('/prompts')
def prompts():
    try:
        search = request.args.get('search', '')
        tool_filter = request.args.get('tool', 'All')
        category_filter = request.args.get('category', 'All')
        difficulty_filter = request.args.get('difficulty', 'All')
        author_filter = request.args.get('author', 'All')
        sort_by = request.args.get('sort', 'popular')
        filter_type = request.args.get('filter', 'all')  # all, bookmarked, my_prompts
        
        prompts = Prompt.query
        
        # Handle filter types
        if filter_type == 'bookmarked' and current_user.is_authenticated:
            # Show only bookmarked prompts for the current user
            prompts = prompts.join(PromptBookmark, Prompt.id == PromptBookmark.prompt_id).filter(
                PromptBookmark.user_id == current_user.id
            )
        elif filter_type == 'my_prompts' and current_user.is_authenticated:
            # Show only prompts uploaded by the current user
            prompts = prompts.filter(Prompt.author_id == current_user.id)
        
        if search:
            prompts = prompts.filter(
                (Prompt.title.contains(search)) |
                (Prompt.content.contains(search)) |
                (Prompt.tags.contains(search))
            )
        if tool_filter != 'All':
            prompts = prompts.filter(Prompt.tool == tool_filter)
        if category_filter != 'All':
            prompts = prompts.filter(Prompt.category == category_filter)
        if difficulty_filter != 'All':
            # This would require adding a difficulty field to the Prompt model
            # For now, we'll filter based on content length as a proxy
            if difficulty_filter == 'Beginner':
                prompts = prompts.filter(db.func.length(Prompt.content) <= 200)
            elif difficulty_filter == 'Intermediate':
                prompts = prompts.filter(db.func.length(Prompt.content) > 200, db.func.length(Prompt.content) <= 500)
            elif difficulty_filter == 'Advanced':
                prompts = prompts.filter(db.func.length(Prompt.content) > 500)
        if author_filter != 'All':
            prompts = prompts.join(User, Prompt.author_id == User.id).filter(User.username == author_filter)
        
        if sort_by == 'popular':
            prompts = prompts.order_by((Prompt.upvotes - Prompt.downvotes).desc())
        elif sort_by == 'recent':
            prompts = prompts.order_by(Prompt.created_at.desc())
        elif sort_by == 'title':
            prompts = prompts.order_by(Prompt.title)
        elif sort_by == 'rating':
            prompts = prompts.order_by((Prompt.upvotes - Prompt.downvotes).desc())
        elif sort_by == 'likes':
            prompts = prompts.order_by(Prompt.likes.desc())
        
        prompts = prompts.all()
        
        # Get unique values for filter dropdowns
        tools = db.session.query(Prompt.tool).distinct().all()
        tools = [tool[0] for tool in tools if tool[0]]
        
        categories = db.session.query(Prompt.category).distinct().all()
        categories = [cat[0] for cat in categories if cat[0]]
        
        authors = db.session.query(User.username).join(Prompt, User.id == Prompt.author_id).distinct().all()
        authors = [author[0] for author in authors if author[0]]
        
        return render_template('prompts.html', prompts=prompts, search=search, 
                             selected_tool=tool_filter, selected_category=category_filter, 
                             selected_difficulty=difficulty_filter, selected_author=author_filter,
                             sort_by=sort_by, filter_type=filter_type, tools=tools, categories=categories, authors=authors)
    except Exception as e:
        print(f"Error in prompts route: {e}")
        import traceback
        traceback.print_exc()
        return render_template('prompts.html', prompts=[], search='', 
                             selected_tool='All', selected_category='All', 
                             selected_difficulty='All', selected_author='All',
                             sort_by='popular', filter_type='all', tools=[], categories=[], authors=[])

@app.route('/community')
def community():
    try:
        tab = request.args.get('tab', 'posts')
        sort_by = request.args.get('sort', 'popular')
        search = request.args.get('search', '')
        filter_type = request.args.get('filter', 'all')  # all, my_posts
        
        posts = []
        if tab in ['posts', 'discussions', 'questions']:
            posts = Post.query
            
            # Handle filter types
            if filter_type == 'my_posts' and current_user.is_authenticated:
                # Show only posts by the current user
                posts = posts.filter(Post.author_id == current_user.id)
            
            # Filter by type for discussions and questions
            if tab == 'discussions':
                posts = posts.filter(Post.type == 'discussion')
            elif tab == 'questions':
                posts = posts.filter(Post.type == 'question')
            
            # Handle search
            if search:
                posts = posts.filter(
                    (Post.title.contains(search)) |
                    (Post.content.contains(search))
                )
            
            # Handle sorting
            if sort_by == 'popular':
                posts = posts.order_by(Post.upvotes.desc())
            elif sort_by == 'recent':
                posts = posts.order_by(Post.created_at.desc())
            elif sort_by == 'discussed':
                posts = posts.order_by(Post.comments.desc())
            
            posts = posts.all()
        
        users = User.query.order_by(User.points.desc()).limit(10).all()
        
        return render_template('community.html', posts=posts, users=users, active_tab=tab, sort_by=sort_by, search=search, filter_type=filter_type)
    except Exception as e:
        return render_template('community.html', posts=[], users=[], active_tab='posts', sort_by='popular', search='', filter_type='all')

@app.route('/dashboard')
@login_required
def dashboard():
    tab = request.args.get('tab', 'overview')
    
    # Get saved tools
    tool_bookmarks = ToolBookmark.query.filter_by(user_id=current_user.id).all()
    saved_tools = [bookmark.tool for bookmark in tool_bookmarks]
    
    # Get saved prompts
    prompt_bookmarks = PromptBookmark.query.filter_by(user_id=current_user.id).all()
    saved_prompts = [bookmark.prompt for bookmark in prompt_bookmarks]
    
    # Get recent activities
    recent_activities = UserActivity.query.filter_by(user_id=current_user.id).order_by(UserActivity.created_at.desc()).limit(5).all()
    
    # Get followed categories
    followed_categories = FollowedCategory.query.filter_by(user_id=current_user.id).all()
    followed_cats = [follow.category for follow in followed_categories]
    
    return render_template('dashboard.html', 
                         user=current_user, 
                         active_tab=tab,
                         saved_tools=saved_tools, 
                         saved_prompts=saved_prompts,
                         recent_activities=recent_activities,
                         followed_categories=followed_cats)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"], deduct_when=lambda response: True)
def login():
    if request.method == 'POST':
        login_identifier = request.form.get('username')  # This field can contain username or email
        password = request.form.get('password')
        
        # Try to find user by username first, then by email
        user = User.query.filter_by(username=login_identifier).first()
        if not user:
            user = User.query.filter_by(email=login_identifier).first()
        
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not getattr(user, 'email_verified', False):
                try:
                    send_verification_email(user)
                except Exception as e:
                    print(f"Resend verification failed: {e}")
                return render_template('login.html', error='Email not verified. We resent a verification link to your email.')
            login_user(user)
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error='Invalid username/email or password')
    
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            return render_template('forgot_password.html', error='Please enter your email address.')
        
        user = User.query.filter_by(email=email).first()
        if user:
            try:
                send_password_reset_email(user)
            except Exception as e:
                print(f"Failed to send password reset email: {e}")
        
        # Always show success message for security (don't reveal if email exists)
        return render_template('forgot_password.html', success='If an account with that email exists, we have sent a password reset link.')
    
    return render_template('forgot_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('token', '')
    if not token:
        return render_template('login.html', error='Invalid reset link.')
    
    # Verify token
    data = verify_password_reset_token(token)
    if not data:
        return render_template('login.html', error='Reset link is invalid or expired.')
    
    user = db.session.get(User, data.get('user_id'))
    if not user or user.email != data.get('email'):
        return render_template('login.html', error='Invalid reset link.')
    
    # Check if token matches and is not expired
    if not user.reset_token or user.reset_token != token:
        return render_template('login.html', error='Invalid reset link.')
    
    if user.reset_token_expires and user.reset_token_expires < datetime.utcnow():
        return render_template('login.html', error='Reset link has expired.')
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or len(password) < 6:
            return render_template('reset_password.html', token=token, error='Password must be at least 6 characters long.')
        
        if password != confirm_password:
            return render_template('reset_password.html', token=token, error='Passwords do not match.')
        
        # Update password and clear reset token
        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()
        
        return render_template('login.html', error='Password reset successfully. You can now sign in with your new password.')
    
    return render_template('reset_password.html', token=token)

@app.route('/verify-email')
def verify_email():
    token = request.args.get('token', '')
    if not token:
        return render_template('login.html', error='Invalid verification link.')
    data = confirm_email_token(token)
    if not data:
        return render_template('login.html', error='Verification link is invalid or expired.')
    user = db.session.get(User, data.get('user_id'))
    if not user or user.email != data.get('email'):
        return render_template('login.html', error='Verification link is invalid.')
    if getattr(user, 'email_verified', False):
        return render_template('login.html', error='Email already verified. Please sign in.')
    if getattr(user, 'email_verification_token', None) and user.email_verification_token != token:
        return render_template('login.html', error='This verification link has been superseded. Please use the latest email.')
    user.email_verified = True
    user.email_verified_at = datetime.utcnow()
    user.email_verification_token = None
    db.session.commit()
    return render_template('login.html', error='Email verified successfully. You can now sign in.')

@app.route('/resend-verification')
def resend_verification():
    email = request.args.get('email')
    if not email:
        return render_template('login.html', error='Please provide an email to resend the verification link.')
    user = User.query.filter_by(email=email).first()
    if not user:
        return render_template('login.html', error='If this email exists, a verification link has been sent.')
    if getattr(user, 'email_verified', False):
        return render_template('login.html', error='Email already verified. Please sign in.')
    try:
        send_verification_email(user)
    except Exception as e:
        print(f"Resend verification failed: {e}")
    return render_template('login.html', error='If this email exists, a verification link has been sent.')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Username already exists')
        
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='Email already registered')
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        try:
            send_verification_email(user)
        except Exception as e:
            print(f"Failed to send verification email: {e}")
        return render_template('login.html', error='Account created. We sent a verification link to your email. Please verify to sign in.')
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

# Legal Pages
@app.route('/privacy')
def privacy():
    """Privacy Policy page"""
    return render_template('privacy_terms.html')

@app.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('privacy_terms.html')

# Google OAuth Routes
@app.route('/login/google')
def google_login():
    """Initiate Google OAuth login"""
    google = get_google()  # Get Google OAuth instance
    if not google:
        return render_template('login.html', error='Google OAuth is not configured. Please contact the administrator.')
    
    try:
        redirect_uri = url_for('google_callback', _external=True)
        return google.authorize_redirect(redirect_uri)
    except Exception as e:
        print(f"Google OAuth error: {e}")
        return render_template('login.html', error='Google OAuth service is currently unavailable. Please try again later.')

@app.route('/callback/google')
def google_callback():
    """Handle Google OAuth callback"""
    google = get_google()  # Get Google OAuth instance
    if not google:
        return render_template('login.html', error='Google OAuth is not configured. Please contact the administrator.')
    
    try:
        # Get the authorization code from the callback
        token = google.authorize_access_token()
        
        # Get user info from Google
        user_info = token.get('userinfo')
        if not user_info:
            return render_template('login.html', error='Failed to get user information from Google')
        
        # Extract user data
        google_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name')
        picture = user_info.get('picture')
        
        if not google_id or not email:
            return render_template('login.html', error='Invalid user information from Google')
        
        # Check if user already exists with this Google ID
        user = User.query.filter_by(google_id=google_id).first()
        
        if not user:
            # Check if user exists with this email (for linking accounts)
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                # Link Google account to existing user
                existing_user.google_id = google_id
                if not existing_user.password_hash:  # If no password set, make it OAuth-only
                    existing_user.password_hash = None
                db.session.commit()
                user = existing_user
            else:
                # Create new user
                # Generate username from email or name
                username = email.split('@')[0]
                # Ensure username is unique
                original_username = username
                counter = 1
                while User.query.filter_by(username=username).first():
                    username = f"{original_username}{counter}"
                    counter += 1
                
                user = User(
                    username=username,
                    email=email,
                    google_id=google_id,
                    password_hash=None,  # OAuth users don't need password
                    avatar='👤'  # Default avatar, could be updated with Google profile picture
                )
                db.session.add(user)
                db.session.commit()
                
                # Record welcome activity
                record_activity(user.id, 'account_created', 10, 'Welcome! Account created with Google')
        
        # Log the user in
        login_user(user)
        
        # Record login activity
        record_activity(user.id, 'login', 1, 'Logged in with Google')
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Google OAuth error: {e}")
        return render_template('login.html', error='Authentication failed. Please try again.')

# API Routes
@app.route('/api/tools')
def api_tools():
    # Add pagination to prevent loading all tools into memory
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)  # Max 100 per page
    
    pagination = Tool.query.paginate(page=page, per_page=per_page, error_out=False)
    tools = pagination.items
    
    return jsonify({
        'tools': [{
            'id': tool.id,
            'name': tool.name,
            'description': tool.description,
            'short_description': tool.short_description,
            'logo': tool.logo,
            'category': tool.category,
            'rating': tool.rating,
            'review_count': tool.review_count,
            'pricing': tool.pricing,
            'website': tool.website,
            'features': json.loads(tool.features) if tool.features else [],
            'integrations': json.loads(tool.integrations) if tool.integrations else [],
            'tags': json.loads(tool.tags) if tool.tags else []
        } for tool in tools],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })

@app.route('/api/prompts')
def api_prompts():
    # Add pagination to prevent loading all prompts into memory
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)  # Max 100 per page
    
    pagination = Prompt.query.paginate(page=page, per_page=per_page, error_out=False)
    prompts = pagination.items
    
    return jsonify({
        'prompts': [{
            'id': prompt.id,
            'title': prompt.title,
            'content': prompt.content,
            'category': prompt.category,
            'tool': prompt.tool,
            'author': prompt.author.username,
            'upvotes': prompt.upvotes,
            'downvotes': prompt.downvotes,
            'tags': json.loads(prompt.tags) if prompt.tags else [],
            'created_at': prompt.created_at.isoformat()
        } for prompt in prompts],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })

@app.route('/api/tools/search')
def api_tools_search():
    """API endpoint to search tools from database"""
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 20, type=int)
    
    if not query:
        # Return popular tools if no query
        tools = Tool.query.order_by(Tool.rating.desc()).limit(limit).all()
    else:
        # Search tools by name
        tools = Tool.query.filter(Tool.name.contains(query)).order_by(Tool.rating.desc()).limit(limit).all()
    
    return jsonify([{
        'id': tool.id,
        'name': tool.name,
        'website': tool.website,
        'description': tool.short_description,
        'category': tool.category,
        'rating': tool.rating
    } for tool in tools])

@app.route('/api/bookmark/tool/<int:tool_id>', methods=['POST'])
@login_required
def bookmark_tool(tool_id):
    tool = Tool.query.get_or_404(tool_id)
    
    # Check if already bookmarked
    existing_bookmark = ToolBookmark.query.filter_by(
        user_id=current_user.id, 
        tool_id=tool_id
    ).first()
    
    if existing_bookmark:
        # Remove bookmark
        db.session.delete(existing_bookmark)
        message = 'Tool removed from bookmarks'
        action = 'unbookmark'
    else:
        # Add bookmark
        bookmark = ToolBookmark(user_id=current_user.id, tool_id=tool_id)
        db.session.add(bookmark)
        message = 'Tool bookmarked successfully'
        action = 'bookmark'
        
        # Record activity and award points
        record_activity(current_user.id, 'bookmark_tool', 2, f'Bookmarked {tool.name}')
        check_badge_conditions(current_user)
    
    db.session.commit()
    return jsonify({
        'success': True, 
        'message': message,
        'action': action
    })

@app.route('/api/bookmark/prompt/<int:prompt_id>', methods=['POST'])
@login_required
def bookmark_prompt(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    
    # Check if already bookmarked
    existing_bookmark = PromptBookmark.query.filter_by(
        user_id=current_user.id, 
        prompt_id=prompt_id
    ).first()
    
    if existing_bookmark:
        # Remove bookmark
        db.session.delete(existing_bookmark)
        message = 'Prompt removed from bookmarks'
        action = 'unbookmark'
    else:
        # Add bookmark
        bookmark = PromptBookmark(user_id=current_user.id, prompt_id=prompt_id)
        db.session.add(bookmark)
        message = 'Prompt bookmarked successfully'
        action = 'bookmark'
        
        # Record activity and award points
        record_activity(current_user.id, 'bookmark_prompt', 2, f'Bookmarked prompt: {prompt.title}')
        check_badge_conditions(current_user)
    
    db.session.commit()
    return jsonify({
        'success': True, 
        'message': message,
        'action': action
    })

# New route specifically for removing bookmarks
@app.route('/api/bookmark/remove/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def remove_bookmark(item_type, item_id):
    if item_type == 'tool':
        bookmark = ToolBookmark.query.filter_by(
            user_id=current_user.id, 
            tool_id=item_id
        ).first()
        if bookmark:
            db.session.delete(bookmark)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Tool removed from bookmarks'
            })
    elif item_type == 'prompt':
        bookmark = PromptBookmark.query.filter_by(
            user_id=current_user.id, 
            prompt_id=item_id
        ).first()
        if bookmark:
            db.session.delete(bookmark)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Prompt removed from bookmarks'
            })
    
    return jsonify({
        'success': False,
        'message': 'Bookmark not found'
    }), 404

@app.route('/api/vote/post/<int:post_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def vote_post(post_id):
    data = request.get_json()
    vote_type = data.get('type', 'upvote')  # 'upvote' or 'downvote'
    post = Post.query.get_or_404(post_id)
    
    # Check if user already voted
    existing_vote = PostVote.query.filter_by(
        user_id=current_user.id, 
        post_id=post_id
    ).first()
    
    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote
            db.session.delete(existing_vote)
            if vote_type == 'upvote':
                post.upvotes -= 1
            else:
                post.downvotes -= 1
            message = f'{vote_type} removed'
            action = 'remove'
        else:
            # Change vote
            if existing_vote.vote_type == 'upvote':
                post.upvotes -= 1
                post.downvotes += 1
            else:
                post.upvotes += 1
                post.downvotes -= 1
            existing_vote.vote_type = vote_type
            message = f'Changed to {vote_type}'
            action = 'change'
    else:
        # New vote
        vote = PostVote(user_id=current_user.id, post_id=post_id, vote_type=vote_type)
        db.session.add(vote)
        if vote_type == 'upvote':
            post.upvotes += 1
        else:
            post.downvotes += 1
        message = f'{vote_type} recorded'
        action = 'add'
        
        # Award points to voter
        points = 1 if vote_type == 'upvote' else 0
        if points > 0:
            record_activity(current_user.id, 'vote_post', points, f'Voted on post: {post.title}')
    
    db.session.commit()
    
    # Notify post author if it's an upvote
    if vote_type == 'upvote' and action == 'add' and post.author_id != current_user.id:
        create_notification(
            post.author_id, 
            'upvote', 
            f'Your post got an upvote', 
            f'"{post.title}" received an upvote from {current_user.username}'
        )
    
    return jsonify({
        'success': True, 
        'message': message,
        'action': action,
        'upvotes': post.upvotes,
        'downvotes': post.downvotes
    })

@app.route('/api/vote/prompt/<int:prompt_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def vote_prompt(prompt_id):
    data = request.get_json()
    vote_type = data.get('type', 'upvote')  # 'upvote' or 'downvote'
    prompt = Prompt.query.get_or_404(prompt_id)
    
    # Check if user already voted
    existing_vote = PromptVote.query.filter_by(
        user_id=current_user.id, 
        prompt_id=prompt_id
    ).first()
    
    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote
            db.session.delete(existing_vote)
            if vote_type == 'upvote':
                prompt.upvotes -= 1
            else:
                prompt.downvotes -= 1
            message = f'{vote_type} removed'
            action = 'remove'
        else:
            # Change vote
            if existing_vote.vote_type == 'upvote':
                prompt.upvotes -= 1
                prompt.downvotes += 1
            else:
                prompt.upvotes += 1
                prompt.downvotes -= 1
            existing_vote.vote_type = vote_type
            message = f'Changed to {vote_type}'
            action = 'change'
    else:
        # New vote
        vote = PromptVote(user_id=current_user.id, prompt_id=prompt_id, vote_type=vote_type)
        db.session.add(vote)
        if vote_type == 'upvote':
            prompt.upvotes += 1
        else:
            prompt.downvotes += 1
        message = f'{vote_type} recorded'
        action = 'add'
        
        # Award points to voter
        points = 1 if vote_type == 'upvote' else 0
        if points > 0:
            record_activity(current_user.id, 'vote_prompt', points, f'Voted on prompt: {prompt.title}')
    
    db.session.commit()
    
    # Notify prompt author if it's an upvote
    if vote_type == 'upvote' and action == 'add' and prompt.author_id != current_user.id:
        create_notification(
            prompt.author_id, 
            'upvote', 
            f'Your prompt got an upvote', 
            f'"{prompt.title}" received an upvote from {current_user.username}'
        )
    
    return jsonify({
        'success': True, 
        'message': message,
        'action': action,
        'upvotes': prompt.upvotes,
        'downvotes': prompt.downvotes
    })

@app.route('/api/like/prompt/<int:prompt_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def like_prompt(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    
    # Check if user already liked
    existing_like = PromptLike.query.filter_by(
        user_id=current_user.id, 
        prompt_id=prompt_id
    ).first()
    
    if existing_like:
        # Unlike
        db.session.delete(existing_like)
        prompt.likes -= 1
        message = 'Prompt unliked'
        action = 'unlike'
    else:
        # Like
        like = PromptLike(user_id=current_user.id, prompt_id=prompt_id)
        db.session.add(like)
        prompt.likes += 1
        message = 'Prompt liked'
        action = 'like'
        
        # Award points to liker
        record_activity(current_user.id, 'like_prompt', 1, f'Liked prompt: {prompt.title}')
    
    db.session.commit()
    
    # Notify prompt author if it's a new like
    if action == 'like' and prompt.author_id != current_user.id:
        create_notification(
            prompt.author_id, 
            'like', 
            f'Your prompt got a like', 
            f'"{prompt.title}" received a like from {current_user.username}'
        )
    
    return jsonify({
        'success': True, 
        'message': message,
        'action': action,
        'likes': prompt.likes
    })

@app.route('/api/like/post/<int:post_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if user already liked
    existing_like = PostLike.query.filter_by(
        user_id=current_user.id, 
        post_id=post_id
    ).first()
    
    if existing_like:
        # Unlike
        db.session.delete(existing_like)
        post.likes -= 1
        message = 'Post unliked'
        action = 'unlike'
    else:
        # Like
        like = PostLike(user_id=current_user.id, post_id=post_id)
        db.session.add(like)
        post.likes += 1
        message = 'Post liked'
        action = 'like'
        
        # Award points to liker
        record_activity(current_user.id, 'like_post', 1, f'Liked post: {post.title}')
    
    db.session.commit()
    
    # Notify post author if it's a new like
    if action == 'like' and post.author_id != current_user.id:
        create_notification(
            post.author_id, 
            'like', 
            f'Your post got a like', 
            f'"{post.title}" received a like from {current_user.username}'
        )
    
    return jsonify({
        'success': True, 
        'message': message,
        'action': action,
        'likes': post.likes
    })

@app.route('/api/recommendations')
def get_recommendations():
    # In a real app, this would use ML to generate personalized recommendations
    recommendations = [
        {
            'id': 1,
            'name': 'ChatGPT',
            'description': 'Based on your writing interests',
            'match_percentage': 95,
            'logo': '🤖',
            'category': 'Writing'
        },
        {
            'id': 2,
            'name': 'Midjourney',
            'description': 'Perfect for your design needs',
            'match_percentage': 88,
            'logo': '🎨',
            'category': 'Design'
        },
        {
            'id': 4,
            'name': 'GitHub Copilot',
            'description': 'Boost your coding productivity',
            'match_percentage': 92,
            'logo': '💻',
            'category': 'Coding'
        }
    ]
    return jsonify(recommendations)

@app.route('/api/leaderboard')
def get_leaderboard():
    """Get full leaderboard with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        # Get all users ordered by points
        users_query = User.query.order_by(User.points.desc())
        pagination = users_query.paginate(page=page, per_page=per_page, error_out=False)
        users = pagination.items
        
        leaderboard = []
        for i, user in enumerate(users):
            # Calculate rank (considering pagination)
            rank = (page - 1) * per_page + i + 1
            
            # Get user badges
            badges = user.get_badges() if hasattr(user, 'get_badges') else []
            
            # Get user stats (optimized with single queries)
            posts_count = db.session.query(db.func.count(Post.id)).filter_by(author_id=user.id).scalar() or 0
            prompts_count = db.session.query(db.func.count(Prompt.id)).filter_by(author_id=user.id).scalar() or 0
            
            leaderboard.append({
                'id': user.id,
                'username': user.username,
                'avatar': user.avatar or '👤',
                'points': user.points or 0,
                'level': user.level or 1,
                'badges': badges,
                'rank': rank,
                'posts_count': posts_count,
                'prompts_count': prompts_count,
                'joined_date': user.created_at.strftime('%B %Y') if hasattr(user, 'created_at') else 'Unknown'
            })
        
        return jsonify({
            'success': True,
            'leaderboard': leaderboard,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'leaderboard': []
        }), 500

@app.route('/api/notifications')
@login_required
def get_notifications():
    notifications = UserNotification.query.filter_by(user_id=current_user.id).order_by(UserNotification.created_at.desc()).limit(10).all()
    
    notification_list = []
    for notification in notifications:
        # Calculate time ago
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        time_diff = now - notification.created_at.replace(tzinfo=timezone.utc)
        
        if time_diff.days > 0:
            timestamp = f"{time_diff.days} day{'s' if time_diff.days != 1 else ''} ago"
        elif time_diff.seconds > 3600:
            hours = time_diff.seconds // 3600
            timestamp = f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            minutes = time_diff.seconds // 60
            timestamp = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        
        notification_list.append({
            'id': notification.id,
            'type': notification.notification_type,
            'title': notification.title,
            'message': notification.message,
            'timestamp': timestamp,
            'read': notification.read
        })
    
    return jsonify(notification_list)

@app.route('/api/notifications/mark-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = UserNotification.query.filter_by(
        id=notification_id, 
        user_id=current_user.id
    ).first()
    
    if notification:
        notification.read = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Notification marked as read'})
    
    return jsonify({'success': False, 'message': 'Notification not found'}), 404

@app.route('/api/test/prompt', methods=['POST'])
def test_prompt():
    data = request.get_json()
    prompt_content = data.get('prompt', '')
    additional_context = data.get('context', '')
    
    # In a real app, this would call actual AI APIs
    # For now, return simulated results
    import time
    time.sleep(1)  # Simulate processing time
    
    return jsonify({
        'success': True,
        'response': 'This is a simulated response from the AI tool. In a real implementation, this would be the actual output from the AI service.',
        'metrics': {
            'response_time': '2.3s',
            'quality_score': 8.5,
            'token_count': 156
        }
    })

@app.route('/api/agent/selftest')
def agent_selftest():
    """Quick health check for the system."""
    status = {
        'system_enabled': True,
        'database_available': True,
        'tools_count': Tool.query.count(),
        'prompts_count': Prompt.query.count(),
        'posts_count': Post.query.count()
    }
    return jsonify(status)

@app.route('/api/edit/prompt/<int:prompt_id>', methods=['PUT'])
@login_required
def edit_prompt(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    
    # Check if user owns this prompt
    if prompt.author_id != current_user.id:
        return jsonify({
            'success': False,
            'message': 'You can only edit your own prompts'
        }), 403
    
    data = request.get_json()
    
    # Validate required fields
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    category = data.get('category', '').strip()
    tool = data.get('tool', '').strip()
    tool_id = data.get('tool_id')
    tool_website = data.get('tool_website', '')
    tags = data.get('tags', [])
    
    if not all([title, content, category, tool]):
        return jsonify({
            'success': False,
            'message': 'All fields are required'
        }), 400
    
    # Update prompt
    prompt.title = title
    prompt.content = content
    prompt.category = category
    prompt.tool = tool
    prompt.tool_id = tool_id
    prompt.tool_website = tool_website
    prompt.tags = json.dumps(tags)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Prompt updated successfully!'
    })
    # unreachable; incremental rebuild handled above if needed

@app.route('/api/delete/prompt/<int:prompt_id>', methods=['DELETE'])
@limiter.limit("5 per hour")
@login_required
def delete_prompt(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    
    # Check if user owns this prompt
    if prompt.author_id != current_user.id:
        return jsonify({
            'success': False,
            'message': 'You can only delete your own prompts'
        }), 403
    
    # Delete the prompt
    db.session.delete(prompt)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Prompt deleted successfully!'
    })
    # unreachable; deletion succeeded

@app.route('/api/edit/post/<int:post_id>', methods=['PUT'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if user owns this post
    if post.author_id != current_user.id:
        return jsonify({
            'success': False,
            'message': 'You can only edit your own posts'
        }), 403
    
    data = request.get_json()
    
    # Validate required fields
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    
    if not all([title, content]):
        return jsonify({
            'success': False,
            'message': 'Title and content are required'
        }), 400
    
    # Update post
    post.title = title
    post.content = content
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Post updated successfully!'
    })
    # unreachable; post updated

@app.route('/api/delete/post/<int:post_id>', methods=['DELETE'])
@limiter.limit("5 per hour")
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if user owns this post
    if post.author_id != current_user.id:
        return jsonify({
            'success': False,
            'message': 'You can only delete your own posts'
        }), 403
    
    # Manually cascade delete related entities to avoid FK issues
    try:
        # Delete comment likes linked to this post's comments
        comment_ids = [c.id for c in PostComment.query.filter_by(post_id=post.id).all()]
        if comment_ids:
            CommentLike.query.filter(CommentLike.comment_id.in_(comment_ids)).delete(synchronize_session=False)
        # Delete post comments (including replies)
        PostComment.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        # Delete post likes
        PostLike.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        # Delete post votes
        PostVote.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        # Finally delete the post
        db.session.delete(post)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Failed to delete post. Please try again.'
        }), 500
    
    return jsonify({
        'success': True,
        'message': 'Post deleted successfully!'
    })
    # unreachable; deletion succeeded

@app.route('/api/upload/prompt', methods=['POST'])
@login_required
def upload_prompt():
    data = request.get_json()
    
    # Validate required fields
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    category = data.get('category', '').strip()
    tool = data.get('tool', '').strip()
    tool_id = data.get('tool_id')
    tool_website = data.get('tool_website', '')
    tags = data.get('tags', [])
    
    if not all([title, content, category, tool]):
        return jsonify({
            'success': False,
            'message': 'All fields are required'
        }), 400
    
    # Create new prompt
    prompt = Prompt(
        title=title,
        content=content,
        category=category,
        tool=tool,
        tool_id=tool_id,
        tool_website=tool_website,
        author_id=current_user.id,
        tags=json.dumps(tags)
    )
    
    db.session.add(prompt)
    db.session.commit()
    
    # Record activity and award points
    record_activity(current_user.id, 'upload_prompt', 10, f'Uploaded prompt: {title}')
    check_badge_conditions(current_user)
    
    return jsonify({
        'success': True,
        'message': 'Prompt uploaded successfully! +10 points earned!',
        'points_earned': 10,
        'prompt_id': prompt.id
    })

@app.route('/api/upload/post', methods=['POST'])
@login_required
def upload_post():
    data = request.get_json()
    
    # Validate required fields
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    post_type = (data.get('type') or 'post').strip()
    tags = data.get('tags', [])
    
    if not all([title, content]):
        return jsonify({
            'success': False,
            'message': 'Title and content are required'
        }), 400
    
    # Create new post
    post = Post(
        title=title,
        content=content,
        author_id=current_user.id,
        type=post_type if post_type in ['post', 'review', 'tutorial', 'question', 'discussion'] else 'post',
        tags=json.dumps(tags)
    )
    
    db.session.add(post)
    db.session.commit()
    
    # Record activity and award points
    record_activity(current_user.id, 'upload_post', 5, f'Created post: {title}')
    check_badge_conditions(current_user)
    
    return jsonify({
        'success': True,
        'message': 'Post created successfully! +5 points earned!',
        'points_earned': 5,
        'post_id': post.id
    })

@app.route('/api/user/stats')
@login_required
def user_stats():
    # Count saved tools
    saved_tools_count = ToolBookmark.query.filter_by(user_id=current_user.id).count()
    
    # Count saved prompts
    saved_prompts_count = PromptBookmark.query.filter_by(user_id=current_user.id).count()
    
    # Count contributions (posts + prompts created)
    posts_created = Post.query.filter_by(author_id=current_user.id).count()
    prompts_shared = Prompt.query.filter_by(author_id=current_user.id).count()
    contributions = posts_created + prompts_shared
    
    # Count total upvotes received (optimized with single queries)
    total_upvotes = (db.session.query(db.func.sum(Post.upvotes)).filter_by(author_id=current_user.id).scalar() or 0) + \
                   (db.session.query(db.func.sum(Prompt.upvotes)).filter_by(author_id=current_user.id).scalar() or 0)
    
    # Calculate leaderboard rank (optimized)
    users_with_higher_points = User.query.filter(User.points > current_user.points).count()
    leaderboard_rank = users_with_higher_points + 1
    
    return jsonify({
        'saved_tools': saved_tools_count,
        'saved_prompts': saved_prompts_count,
        'contributions': contributions,
        'posts_created': posts_created,
        'prompts_shared': prompts_shared,
        'reviews_written': 0,  # TODO: Implement reviews system
        'total_upvotes': total_upvotes,
        'leaderboard_rank': leaderboard_rank,
        'points': current_user.points,
        'level': current_user.level,
        'badges': current_user.get_badges()
    })

@app.route('/api/follow/category/<int:category_id>', methods=['POST'])
@login_required
def follow_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Check if already following
    existing_follow = FollowedCategory.query.filter_by(
        user_id=current_user.id, 
        category_id=category_id
    ).first()
    
    if existing_follow:
        # Unfollow
        db.session.delete(existing_follow)
        message = f'Unfollowed {category.name}'
        action = 'unfollow'
    else:
        # Follow
        follow = FollowedCategory(user_id=current_user.id, category_id=category_id)
        db.session.add(follow)
        message = f'Now following {category.name}'
        action = 'follow'
        
        # Record activity
        record_activity(current_user.id, 'follow_category', 1, f'Started following {category.name}')
    
    db.session.commit()
    return jsonify({
        'success': True, 
        'message': message,
        'action': action
    })

@app.route('/api/user/followed-categories')
@login_required
def followed_categories():
    follows = FollowedCategory.query.filter_by(user_id=current_user.id).all()
    categories = []
    for follow in follows:
        category = follow.category
        categories.append({
            'id': category.id,
            'name': category.name, 
            'icon': category.icon, 
            'tool_count': category.tool_count
        })
    return jsonify(categories)

@app.route('/api/post/<int:post_id>')
def get_post(post_id):
    post = Post.query.get_or_404(post_id)
    return jsonify({
        'id': post.id,
        'title': post.title,
        'content': post.content,
        'author': {
            'username': post.author.username,
            'avatar': post.author.avatar
        },
        'created_at': post.created_at.strftime('%b %d, %Y'),
        'upvotes': post.upvotes or 0,
        'comments': post.comments or 0,
        'tags': json.loads(post.tags) if post.tags else []
    })

# Additional comment API endpoints to match frontend expectations
@app.route('/api/comments/post/<int:post_id>', methods=['GET'])
def get_comments_for_post(post_id):
    """Get all comments for a specific post"""
    post = Post.query.get_or_404(post_id)
    # Get only top-level comments (not replies)
    comments = PostComment.query.filter_by(post_id=post_id, parent_comment_id=None).order_by(PostComment.created_at.asc()).all()
    
    comments_data = []
    for comment in comments:
        # Get replies for this comment
        replies = PostComment.query.filter_by(parent_comment_id=comment.id).order_by(PostComment.created_at.asc()).all()
        replies_data = []
        
        for reply in replies:
            reply_data = {
                'id': reply.id,
                'content': reply.content,
                'created_at': reply.created_at.isoformat(),
                'author': {
                    'username': reply.user.username,
                    'avatar': reply.user.avatar or '👤'
                },
                'likes': reply.likes or 0
            }
            replies_data.append(reply_data)
        
        comment_data = {
            'id': comment.id,
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
            'author': {
                'username': comment.user.username,
                'avatar': comment.user.avatar or '👤'
            },
            'likes': comment.likes or 0,
            'replies': replies_data
        }
        comments_data.append(comment_data)
    
    return jsonify({
        'success': True,
        'comments': comments_data
    })

@app.route('/api/comment/post/<int:post_id>', methods=['POST'])
@login_required
def create_comment_for_post(post_id):
    """Create a new comment for a specific post"""
    post = Post.query.get_or_404(post_id)
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    
    if not content:
        return jsonify({
            'success': False,
            'message': 'Comment cannot be empty'
        }), 400
    
    comment = PostComment(
        post_id=post_id,
        user_id=current_user.id,
        content=content
    )
    db.session.add(comment)
    
    # Update post comments count
    post.comments = (post.comments or 0) + 1
    
    # Record activity and award points
    record_activity(current_user.id, 'comment_post', 2, f'Commented on post: {post.title}')
    check_badge_conditions(current_user)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Comment posted successfully!',
        'comment_id': comment.id,
        'comments_count': post.comments
    })

@app.route('/api/like/comment/<int:comment_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def like_comment(comment_id):
    """Like or unlike a comment"""
    comment = PostComment.query.get_or_404(comment_id)
    
    # Check if user already liked this comment
    existing_like = CommentLike.query.filter_by(
        user_id=current_user.id,
        comment_id=comment_id
    ).first()
    
    if existing_like:
        # Unlike
        db.session.delete(existing_like)
        comment.likes = max(0, (comment.likes or 0) - 1)
        message = 'Comment unliked'
        action = 'unlike'
    else:
        # Like
        like = CommentLike(
            user_id=current_user.id,
            comment_id=comment_id
        )
        db.session.add(like)
        comment.likes = (comment.likes or 0) + 1
        message = 'Comment liked'
        action = 'like'
        
        # Award points to liker
        record_activity(current_user.id, 'like_comment', 1, f'Liked a comment')
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': message,
        'action': action,
        'likes': comment.likes
    })

@app.route('/api/reply/comment/<int:comment_id>', methods=['POST'])
@login_required
def reply_to_comment(comment_id):
    """Reply to a comment"""
    parent_comment = PostComment.query.get_or_404(comment_id)
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    
    if not content:
        return jsonify({
            'success': False,
            'message': 'Reply cannot be empty'
        }), 400
    
    # Create a reply linked to the parent comment
    reply = PostComment(
        post_id=parent_comment.post_id,
        user_id=current_user.id,
        parent_comment_id=comment_id,  # Link to parent comment
        content=content
    )
    db.session.add(reply)
    
    # Update post comments count
    post = db.session.get(Post, reply.post_id)
    post.comments = (post.comments or 0) + 1
    
    # Record activity and award points
    record_activity(current_user.id, 'reply_comment', 1, f'Replied to comment')
    check_badge_conditions(current_user)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Reply posted successfully!',
        'reply_id': reply.id
    })

@app.route('/api/like/reply/<int:reply_id>', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def like_reply(reply_id):
    """Like or unlike a reply (replies are also comments, so we use the same logic)"""
    reply = PostComment.query.get_or_404(reply_id)
    
    # Check if user already liked this reply
    existing_like = CommentLike.query.filter_by(
        user_id=current_user.id,
        comment_id=reply_id
    ).first()
    
    if existing_like:
        # Unlike
        db.session.delete(existing_like)
        reply.likes = max(0, (reply.likes or 0) - 1)
        message = 'Reply unliked'
        action = 'unlike'
    else:
        # Like
        like = CommentLike(
            user_id=current_user.id,
            comment_id=reply_id
        )
        db.session.add(like)
        reply.likes = (reply.likes or 0) + 1
        message = 'Reply liked'
        action = 'like'
        
        # Award points to liker
        record_activity(current_user.id, 'like_reply', 1, f'Liked a reply')
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': message,
        'action': action,
        'likes': reply.likes
    })

@app.route('/post/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post_detail.html', post=post)

@app.route('/api/user/saved-items')
@login_required
def saved_items():
    # Get saved tools
    tool_bookmarks = ToolBookmark.query.filter_by(user_id=current_user.id).all()
    saved_tools = []
    for bookmark in tool_bookmarks:
        tool = bookmark.tool
        saved_tools.append({
            'id': tool.id,
            'name': tool.name,
            'description': tool.short_description,
            'logo': tool.logo,
            'category': tool.category,
            'pricing': tool.pricing,
            'bookmarked_at': bookmark.created_at.isoformat()
        })
    
    # Get saved prompts
    prompt_bookmarks = PromptBookmark.query.filter_by(user_id=current_user.id).all()
    saved_prompts = []
    for bookmark in prompt_bookmarks:
        prompt = bookmark.prompt
        saved_prompts.append({
            'id': prompt.id,
            'title': prompt.title,
            'tool': prompt.tool,
            'category': prompt.category,
            'bookmarked_at': bookmark.created_at.isoformat()
        })
    
    return jsonify({
        'tools': saved_tools,
        'prompts': saved_prompts
    })

# Internal API endpoint for tool ingestion
@app.route('/internal/tools/ingest', methods=['POST'])
def ingest_tool_endpoint():
    """
    Internal API endpoint to ingest a new tool into the database.
    Calls the ingest_tool() function from ingestion.py
    """
    from ingestion import ingest_tool
    
    # Read JSON from request
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    # Call ingest_tool function
    result, success = ingest_tool(data)
    
    # Return appropriate response
    if success:
        return jsonify(result), 201
    else:
        return jsonify(result), 400


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        
        # Lightweight migration: ensure 'type' column exists on 'post' table
        try:
            if 'post' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('post')]
                if 'type' not in columns:
                    db.session.execute(text("ALTER TABLE post ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'post'"))
                    db.session.commit()
        except Exception as e:
            # Rollback any failed transaction and don't block app startup
            db.session.rollback()
            pass
        
        # Lightweight migration: ensure 'google_id' column exists on 'user' table
        try:
            if 'user' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('user')]
                if 'google_id' not in columns:
                    db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN google_id VARCHAR(50)"))
                    db.session.commit()
                    print("✅ Added google_id column to user table")
        except Exception as e:
            # Rollback any failed transaction and don't block app startup
            db.session.rollback()
            print(f"Migration warning: {e}")
            pass

        
        
        # Create tables if they don't exist (for PostgreSQL)
        try:
            db.create_all()
            print("✅ Database tables created/verified")
        except Exception as e:
            print(f"⚠️  Database table creation warning: {e}")
        
        # Initialize with sample data if database is empty
        try:
            if not Tool.query.first():
                from sample_data import create_sample_data
                create_sample_data()
        except Exception as e:
            # Rollback any failed transaction
            db.session.rollback()
            print(f"⚠️  Sample data initialization warning: {e}")
            print("💡 This is normal if tables are empty or don't exist yet")

        print("🚀 Starting ANY SITE HUB...")
    
    app.run(debug=True, host='0.0.0.0', port=5000) 
