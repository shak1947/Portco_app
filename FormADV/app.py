"""
Form ADV RAG System - Complete Flask API
Retrieves from vector store, synthesizes with Claude
"""

import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
import chromadb
from openai import OpenAI
from anthropic import Anthropic
import logging

load_dotenv()

app = Flask(__name__, template_folder='templates')
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize vector store
chroma_client = chromadb.PersistentClient(path="Data/chroma_openai")
collection = chroma_client.get_or_create_collection(name="form_adv")


class RAGPipeline:
    """Complete RAG pipeline: retrieve + synthesize"""

    def __init__(self, top_k: int = 5, model: str = "claude-sonnet-4-6"):
        self.top_k = top_k
        self.model = model
        self.system_prompt = """You are a PE due diligence analyst with access to Form ADV documents.
Answer questions based on the provided excerpts. Always cite your sources clearly.
If information is not in the excerpts, say "This information is not available in the provided documents."

Available firms:
1. Bain & Company
2. Clayton Dubilier & Rice
3. CVC Capital Partners
4. EQT Partners
5. Hellman & Friedman
6. Kelso & Company
7. TA Associates
8. Thoma Bravo
9. Visa Inc.
10. Warburg Pincus"""

    def retrieve(self, question: str) -> dict:
        """Step 1: Embed question and retrieve relevant chunks"""
        logger.info(f"Retrieving chunks for: {question}")

        # Embed question
        embedding_response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=question
        )
        query_embedding = embedding_response.data[0].embedding

        # Search vector store
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k
        )

        chunks = []
        if results["ids"] and results["ids"][0]:
            for i, (chunk_id, distance, metadata, text) in enumerate(
                zip(
                    results["ids"][0],
                    results["distances"][0],
                    results["metadatas"][0],
                    results["documents"][0]
                )
            ):
                similarity = 1 - distance
                chunks.append({
                    "rank": i + 1,
                    "firm_name": metadata.get("firm_name"),
                    "page_number": metadata.get("page_number"),
                    "source_file": metadata.get("source_file"),
                    "similarity": round(similarity, 3),
                    "text": text
                })

        logger.info(f"Retrieved {len(chunks)} chunks")
        return {"chunks": chunks, "count": len(chunks)}

    def synthesize(self, question: str, chunks: list) -> str:
        """Step 2: Use Claude to synthesize answer from chunks"""
        logger.info("Synthesizing answer with Claude")

        # Build context from chunks
        context_parts = []
        for chunk in chunks:
            context_parts.append(
                f"[{chunk['firm_name']} | Page {chunk['page_number']}]\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # Call Claude with prompt caching
        response = anthropic_client.messages.create(
            model=self.model,
            max_tokens=1024,
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
        """Complete RAG pipeline: retrieve -> synthesize"""
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
        # Verify connections
        collection.count()
        return jsonify({
            "status": "healthy",
            "vector_store": "connected",
            "chunks_indexed": collection.count()
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.route("/api/firms", methods=["GET"])
def get_firms():
    """List available firms"""
    firms = [
        "Bain & Company",
        "Clayton Dubilier & Rice",
        "CVC Capital Partners",
        "EQT Partners",
        "Hellman & Friedman",
        "Kelso & Company",
        "TA Associates",
        "Thoma Bravo",
        "Visa Inc.",
        "Warburg Pincus"
    ]
    return jsonify({"firms": firms, "count": len(firms)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"
    logger.info(f"Starting Form ADV RAG API on port {port}")
    logger.info(f"Vector store: Data/chroma_openai ({collection.count()} chunks)")
    logger.info(f"Debug mode: {debug}")
    app.run(host="0.0.0.0", debug=debug, port=port)
