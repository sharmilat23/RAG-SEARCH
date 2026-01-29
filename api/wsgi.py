import os

# Ensure the app can find project modules when running on Vercel
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in os.sys.path:
    os.sys.path.insert(0, PROJECT_ROOT)

from vercel_wsgi import handle
from app import app as flask_app


def handler(event, context):
    return handle(event, context, flask_app)





