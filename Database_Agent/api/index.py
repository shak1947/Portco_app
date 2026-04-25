"""
Vercel API handler for the Flask app
"""
from app import app

export = app.wsgi_app
