"""
Vercel API handler for the Flask app
"""
import sys
import os

# Add Database_Agent directory to path so we can import app
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Database_Agent'))

from app import app

# Vercel expects the WSGI app
app = app
