"""
Phase 3: FastAPI backend for the Form ADV Research Assistant.
Wraps the Phase 2 query module and serves a single-file frontend.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.query import ask

app = FastAPI(title="Form ADV Research Assistant")

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class QueryRequest(BaseModel):
    """Request body for a query."""
    question: str
    top_k: int = 5


@app.get("/")
def root():
    """Serve the frontend."""
    return FileResponse("static/index.html")


@app.post("/api/query")
def query(req: QueryRequest) -> dict:
    """Process a query and return answer + sources."""
    result = ask(req.question, top_k=req.top_k, chroma_path="data/chroma_openai")
    return {
        "question": result.question,
        "answer": result.answer,
        "sources": [
            {
                "firm_name": s.firm_name,
                "page_number": s.page_number,
                "source_file": s.source_file,
                "similarity": round(s.similarity, 4),
                "excerpt": s.excerpt,
            }
            for s in result.sources
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
