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
import time

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

ANSWER STYLE - Keep answers SHORT, CLEAR, and HUMAN-READABLE:
- 2-4 sentences maximum (unless the question explicitly asks for detailed information)
- Use plain language, avoid raw data dumps or copy-pasting excerpts
- Synthesize key information, don't repeat raw text
- Lead with the direct answer, then cite sources
- For numbers/data, use clear formatting (e.g., "AUM: $5B" not raw copied text)

CRITICAL RULES:
1. ONLY use information from the provided excerpts - no external knowledge
2. If answer not in excerpts, say "This information is not available in the documents"
3. Always cite firm name and relevant section when citing
4. Be precise and factual - avoid speculation or hedging language
5. For comparisons, show side-by-side differences clearly
6. For investment strategies, focus on: approach, fees, fund types, key metrics
7. Extract key facts and synthesize into readable prose, not bullet points

Firms in database: Bain & Company, CD&R, CVC Capital Partners, EQT Partners, Hellman & Friedman, Kelso & Company, TA Associates

FORMATTING:
- Use paragraphs, not lists or raw data
- Highlight numbers with context (e.g., "$50M in AUM" not just "$50M")
- Be concise and direct - edit out verbose language"""

    def retrieve(self, question: str) -> dict:
        """Vector search in Supabase for relevant chunks."""
        logger.info(f"Retrieving chunks for: {question}")
        retrieval_start = time.time()
        pipeline_steps = []

        if not supabase:
            return {"chunks": [], "count": 0, "error": "Supabase not connected"}

        try:
            # Step 1: Analyze question and detect firm filter
            step1_start = time.time()
            firm_filter = None
            firm_mapping = {
                "bain": "Bain",
                "cdr": "CD&R",
                "clayton": "CD&R",
                "cvc": "CVC",
                "eqt": "EQT",
                "hellman": "Hellman",
                "kelso": "Kelso",
                "ta": "TA Associate"
            }

            question_lower = question.lower()
            question_normalized = question_lower.replace("&", "").replace(" and ", "")

            for keyword, firm_name in firm_mapping.items():
                if keyword in question_normalized:
                    firm_filter = firm_name
                    logger.info(f"Detected firm filter: {firm_filter}")
                    break

            pipeline_steps.append({
                "step": 1,
                "name": "Query Analysis",
                "duration_ms": round((time.time() - step1_start) * 1000),
                "details": f"Firm filter detected: {firm_filter if firm_filter else 'None (searching all firms)'}"
            })

            # Step 2: Generate embedding
            step2_start = time.time()
            embedding_response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=question
            )
            query_embedding = embedding_response.data[0].embedding
            embedding_time = round((time.time() - step2_start) * 1000)

            pipeline_steps.append({
                "step": 2,
                "name": "Embedding Generation",
                "duration_ms": embedding_time,
                "details": f"Model: text-embedding-3-small | Dimensions: 1536"
            })
            logger.info(f"Embedding generated in {embedding_time}ms")

            # Step 3: Vector similarity search
            step3_start = time.time()
            limit = min(self.top_k * 3, 30)

            try:
                # Try RPC vector search first
                response = supabase.rpc(
                    "match_documents",
                    {
                        "query_embedding": query_embedding,
                        "match_count": limit,
                        "match_threshold": 0.1
                    }
                ).execute()
                matches = response.data if response.data else []

                # If RPC returned no results, fall back to direct query
                if not matches:
                    logger.info("RPC returned 0 results, falling back to direct query")
                    query = supabase.table("form_adv_embeddings").select(
                        "id, firm_name, source_file, page_number, text"
                    )
                    if firm_filter:
                        query = query.eq("firm_name", firm_filter)
                    response = query.limit(limit).execute()
                    matches = response.data if response.data else []
                    search_method = "direct query with local similarity"
                else:
                    search_method = "pgvector RPC"

            except Exception as e:
                logger.warning(f"Vector search RPC failed: {e}, falling back to direct query")
                query = supabase.table("form_adv_embeddings").select(
                    "id, firm_name, source_file, page_number, text, embedding"
                )
                if firm_filter:
                    query = query.eq("firm_name", firm_filter)
                response = query.limit(100).execute()

                # Compute similarity locally as fallback
                matches = []
                if response.data:
                    similarities = []
                    for item in response.data:
                        try:
                            embedding = item.get("embedding")
                            if isinstance(embedding, str):
                                embedding = json.loads(embedding)
                            db_embedding = np.array(embedding, dtype=np.float32)

                            similarity = np.dot(query_embedding, db_embedding) / (
                                np.linalg.norm(query_embedding) * np.linalg.norm(db_embedding)
                            )
                            similarities.append((similarity, item))
                        except:
                            continue

                    similarities.sort(reverse=True, key=lambda x: x[0])
                    matches = [s[1] for s in similarities[:limit]]

                search_method = "direct query with local similarity (fallback)"

            retrieval_time = round((time.time() - step3_start) * 1000)
            pipeline_steps.append({
                "step": 3,
                "name": "Vector Similarity Search",
                "duration_ms": retrieval_time,
                "details": f"Method: {search_method} | Limit: {limit} | Results: {len(matches)}"
            })
            logger.info(f"Retrieved {len(matches)} matches in {retrieval_time}ms")

            if not matches:
                logger.info("No relevant chunks found")
                pipeline_steps.append({
                    "step": 4,
                    "name": "Result Processing",
                    "duration_ms": 0,
                    "details": "No chunks met threshold - returning empty result"
                })
                return {"chunks": [], "count": 0, "pipeline": pipeline_steps}

            # Step 4: Format results with firm diversity
            step4_start = time.time()
            chunks = []
            firm_counts = {}
            max_per_firm = 2

            for match in matches:
                firm = match.get("firm_name", "Unknown")
                firm_counts[firm] = firm_counts.get(firm, 0) + 1

                if firm_counts[firm] > max_per_firm:
                    continue

                chunks.append({
                    "rank": len(chunks) + 1,
                    "firm_name": firm,
                    "page_number": match.get("page_number", 0),
                    "source_file": match.get("source_file", "Unknown"),
                    "similarity": round(float(match.get("similarity", 0)), 3),
                    "text": match.get("text", "")
                })

                if len(chunks) >= self.top_k:
                    break

            processing_time = round((time.time() - step4_start) * 1000)
            firm_breakdown = {firm: count for firm, count in firm_counts.items() if count > 0}

            pipeline_steps.append({
                "step": 4,
                "name": "Result Processing",
                "duration_ms": processing_time,
                "details": f"Chunks selected: {len(chunks)} | Firm diversity applied: {firm_breakdown}"
            })

            logger.info(f"Retrieved {len(chunks)} chunks with firm diversity in {processing_time}ms")
            return {"chunks": chunks, "count": len(chunks), "pipeline": pipeline_steps}

        except Exception as e:
            logger.error(f"Retrieval error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"chunks": [], "count": 0, "error": str(e)}

    def synthesize(self, question: str, chunks: list) -> tuple:
        """Use Claude to synthesize answer from chunks. Returns (answer, metrics)."""
        logger.info("Synthesizing answer with Claude")
        synthesis_start = time.time()

        # Build context from chunks
        context_parts = []
        for chunk in chunks:
            context_parts.append(
                f"[{chunk['firm_name']} | Page {chunk['page_number']}]\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # Call Claude (reduced tokens to encourage concise answers)
        response = anthropic_client.messages.create(
            model=self.model,
            max_tokens=512,
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
                    "content": f"""Based on the Form ADV excerpts below, answer this question in 2-4 clear sentences. Synthesize the information into readable prose - don't copy raw text or dump data. Lead with a direct answer, then cite sources.

Form ADV Excerpts:
{context}

---

Question: {question}

Your answer (concise, 2-4 sentences, cite sources):"""
                }
            ]
        )

        answer = response.content[0].text
        synthesis_time = round((time.time() - synthesis_start) * 1000)
        logger.info(f"Answer synthesized in {synthesis_time}ms")

        metrics = {
            "model": self.model,
            "duration_ms": synthesis_time,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_tokens": getattr(response.usage, 'cache_read_input_tokens', 0),
            "cache_creation_tokens": getattr(response.usage, 'cache_creation_input_tokens', 0)
        }

        return answer, metrics

    def query(self, question: str) -> dict:
        """Complete RAG pipeline: retrieve -> synthesize with detailed metrics."""
        pipeline_start = time.time()
        pipeline_steps = []

        retrieval = self.retrieve(question)
        chunks = retrieval["chunks"]
        retrieval_pipeline = retrieval.get("pipeline", [])
        pipeline_steps.extend(retrieval_pipeline)

        if not chunks:
            answer = "No relevant information found in the documents."
            synthesis_metrics = {
                "model": self.model,
                "duration_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0
            }
        else:
            answer, synthesis_metrics = self.synthesize(question, chunks)

        total_time = round((time.time() - pipeline_start) * 1000)

        # Add synthesis step
        pipeline_steps.append({
            "step": 5,
            "name": "Answer Synthesis",
            "duration_ms": synthesis_metrics.get("duration_ms", 0),
            "details": f"Model: {synthesis_metrics.get('model')} | Input tokens: {synthesis_metrics.get('input_tokens', 0)} | Output tokens: {synthesis_metrics.get('output_tokens', 0)}"
        })

        # Add completion step
        pipeline_steps.append({
            "step": 6,
            "name": "Pipeline Complete",
            "duration_ms": total_time,
            "details": f"Total end-to-end time: {total_time}ms"
        })

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
            "chunk_count": len(chunks),
            "pipeline_details": pipeline_steps,
            "total_time_ms": total_time
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
