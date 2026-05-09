"""
Form ADV RAG System - Flask API with Supabase pgvector backend
Retrieves embeddings from Supabase, synthesizes with Claude
"""

import os
import json
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from anthropic import Anthropic
from supabase import create_client, Client
import logging
import numpy as np

load_dotenv()

app = Flask(__name__, template_folder='templates')
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize Supabase (requires SUPABASE_URL and SUPABASE_KEY env vars)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase connected")
    except Exception as e:
        logger.error(f"Supabase connection failed: {e}")
else:
    logger.error("SUPABASE_URL or SUPABASE_KEY not set")


class RAGPipeline:
    """RAG pipeline: retrieve embeddings from Supabase + synthesize with Claude"""

    def __init__(self, top_k: int = 10, model: str = "claude-opus-4-7"):
        self.top_k = top_k
        self.model = model
        self.system_prompt = """You are a PE due diligence analyst analyzing Form ADV documents.

CRITICAL RULES:
1. ONLY answer based on the provided excerpts - do not use external knowledge
2. If the answer is not in the excerpts, explicitly say so
3. Always cite which firm and section the information comes from
4. Be precise and factual - avoid speculation
5. If excerpts are unclear or contradictory, acknowledge this
6. For investment strategies, discuss fees, AUM, fund types, and performance
7. Quote directly from documents when possible

Available firms in the database:
- Bain & Company
- CD&R (Clayton Dubilier & Rice)
- CVC Capital Partners
- EQT Partners
- Hellman & Friedman
- Kelso & Company
- TA Associates"""

    def retrieve(self, question: str) -> dict:
        """Vector search in Supabase for relevant chunks."""
        logger.info(f"Retrieving chunks for: {question}")

        if not supabase:
            return {"chunks": [], "count": 0, "error": "Supabase not connected"}

        try:
            # Embed the question
            embedding_response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=question
            )
            query_embedding = np.array(embedding_response.data[0].embedding, dtype=np.float32)
            logger.info(f"Generated embedding, shape: {query_embedding.shape}")

            # Fetch embeddings from Supabase
            response = supabase.table("form_adv_embeddings").select(
                "id, firm_name, source_file, page_number, text, embedding"
            ).limit(500).execute()

            logger.info(f"Fetched {len(response.data)} embeddings from Supabase")

            if not response.data:
                logger.info("No embeddings found in Supabase")
                return {"chunks": [], "count": 0}

            # Compute cosine similarity
            similarities = []
            for item in response.data:
                try:
                    # Parse embedding if it's a string (Supabase returns as JSON string)
                    embedding = item["embedding"]
                    if isinstance(embedding, str):
                        embedding = json.loads(embedding)

                    db_embedding = np.array(embedding, dtype=np.float32)

                    # Verify shapes match
                    if len(query_embedding) != len(db_embedding):
                        logger.warning(f"Embedding size mismatch: {len(query_embedding)} vs {len(db_embedding)}")
                        continue

                    # Cosine similarity
                    similarity = np.dot(query_embedding, db_embedding) / (
                        np.linalg.norm(query_embedding) * np.linalg.norm(db_embedding)
                    )
                    similarities.append((similarity, item))
                except Exception as e:
                    logger.warning(f"Error processing embedding {item.get('id')}: {e}")
                    continue

            logger.info(f"Computed similarities for {len(similarities)} items")

            # Sort by similarity and take top_k
            similarities.sort(reverse=True, key=lambda x: x[0])

            # Filter by minimum similarity threshold (0.3 for decent relevance)
            min_similarity = 0.3
            top_results = [s for s in similarities[:self.top_k] if s[0] >= min_similarity]

            if not top_results:
                logger.info("No chunks met minimum similarity threshold")
                return {"chunks": [], "count": 0}

            # Deduplicate: limit to 2 chunks per firm to avoid redundancy
            chunks = []
            firm_counts = {}
            max_per_firm = 2

            for similarity, match in top_results:
                firm = match.get("firm_name", "Unknown")
                firm_counts[firm] = firm_counts.get(firm, 0) + 1

                # Skip if we already have enough from this firm
                if firm_counts[firm] > max_per_firm:
                    continue

                chunks.append({
                    "rank": len(chunks) + 1,
                    "firm_name": firm,
                    "page_number": match.get("page_number", 0),
                    "source_file": match.get("source_file", "Unknown"),
                    "similarity": round(float(similarity), 3),
                    "text": match.get("text", "")
                })

            logger.info(f"Retrieved {len(chunks)} chunks (filtered by similarity >= {min_similarity})")
            return {"chunks": chunks, "count": len(chunks)}

        except Exception as e:
            logger.error(f"Retrieval error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"chunks": [], "count": 0, "error": str(e)}

    def synthesize(self, question: str, chunks: list) -> str:
        """Use Claude to synthesize answer from chunks."""
        logger.info("Synthesizing answer with Claude")

        # Build context from chunks
        context_parts = []
        for chunk in chunks:
            context_parts.append(
                f"[{chunk['firm_name']} | Page {chunk['page_number']}]\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # Call Claude
        response = anthropic_client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"""Form ADV Excerpts:

{context}

---

Question: {question}

Answer based on the excerpts above and cite your sources."""
                }
            ]
        )

        answer = response.content[0].text
        logger.info("Answer synthesized")
        return answer

    def query(self, question: str) -> dict:
        """Complete RAG pipeline: retrieve -> synthesize."""
        retrieval = self.retrieve(question)
        chunks = retrieval["chunks"]

        if not chunks:
            answer = "No relevant information found in the documents."
        else:
            answer = self.synthesize(question, chunks)

        return {
            "question": question,
            "answer": answer,
            "sources": [
                {
                    "rank": c["rank"],
                    "firm": c["firm_name"],
                    "page": c["page_number"],
                    "similarity": c["similarity"]
                }
                for c in chunks
            ],
            "chunk_count": len(chunks)
        }


# Initialize pipeline
pipeline = RAGPipeline()


@app.route("/")
def index():
    """Serve frontend HTML"""
    return render_template("index.html")


@app.route("/api/query", methods=["POST"])
def api_query():
    """RAG query endpoint"""
    try:
        data = request.json
        question = data.get("question", "").strip()

        if not question:
            return jsonify({"error": "Question cannot be empty"}), 400

        result = pipeline.query(question)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in query: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    try:
        if not supabase:
            return jsonify({"status": "unhealthy", "error": "Supabase not connected"}), 500

        # Verify table exists by fetching one row
        response = supabase.table("form_adv_embeddings").select("id").limit(1).execute()

        # If table exists and has data, it's healthy
        has_data = len(response.data) > 0 if response.data else False

        return jsonify({
            "status": "healthy",
            "vector_store": "supabase_pgvector",
            "table_ready": has_data
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.route("/api/firms", methods=["GET"])
def get_firms():
    """List available firms"""
    firms = [
        "Bain & Company",
        "CD&R (Clayton Dubilier & Rice)",
        "CVC Capital Partners",
        "EQT Partners",
        "Hellman & Friedman",
        "Kelso & Company",
        "TA Associates"
    ]
    return jsonify({"firms": firms, "count": len(firms)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"
    logger.info(f"Starting Form ADV RAG API on port {port}")
    logger.info(f"Backend: Supabase pgvector")
    logger.info(f"Debug mode: {debug}")
    app.run(host="0.0.0.0", debug=debug, port=port)
