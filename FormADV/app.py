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
        print("[RETRIEVE] Starting for: {}".format(question[:50]), flush=True)
        retrieval_start = time.time()
        pipeline_steps = []

        if not supabase:
            print("[RETRIEVE] ERROR: Supabase not connected!", flush=True)
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
                logger.info(f"Calling RPC: limit={limit}, firm_filter={firm_filter}")
                logger.info(f"DEBUG: RPC call - embedding shape={len(query_embedding)}")
                response = supabase.rpc(
                    "match_documents",
                    {
                        "query_embedding": query_embedding,
                        "match_count": limit,
                        "match_threshold": 0.0,
                        "firm_name_filter": firm_filter
                    }
                ).execute()
                matches = response.data if response.data else []
                logger.info(f"DEBUG: RPC response.data type: {type(response.data)}, length: {len(matches)}")
                logger.info(f"RPC returned {len(matches)} results")
                if matches:
                    logger.info(f"  Top match: {matches[0].get('firm_name')} (similarity: {matches[0].get('similarity')})")
                search_method = "pgvector RPC"
            except Exception as e:
                logger.error(f"RPC error: {e}")
                logger.warning(f"Falling back to direct query")
                query = supabase.table("form_adv_embeddings").select(
                    "id, firm_name, source_file, page_number, text"
                )
                if firm_filter:
                    query = query.eq("firm_name", firm_filter)
                    logger.info(f"Filtering to firm: {firm_filter}")
                response = query.limit(limit).execute()
                matches = response.data if response.data else []
                logger.info(f"Fallback returned {len(matches)} results")
                search_method = "direct query (fallback)"

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

    def query_agentic(self, question: str) -> dict:
        """Multi-agent coordinator: Main agent plans, sub-agents answer per-firm questions, coordinator synthesizes."""
        start_time = time.time()
        pipeline_steps = []
        logger.info(f"[COORDINATOR] Received: {question}")

        # Get all firms from database (with limit to avoid fetching all rows)
        try:
            logger.info(f"[COORDINATOR] Fetching firms from database...")
            response = supabase.table("form_adv_embeddings").select("firm_name", count="exact").limit(1000).execute()
            # Get unique firm names from the limited set
            firms = sorted(list(set([row["firm_name"] for row in response.data if row.get("firm_name")])))
            logger.info(f"[COORDINATOR] Found {len(firms)} unique firms from {len(response.data)} rows: {firms}")
        except Exception as e:
            logger.error(f"[COORDINATOR] Failed to fetch firms: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"question": question, "answer": "Error retrieving firms.", "error": str(e)}

        if not firms:
            return {"question": question, "answer": "No firms in database."}

        # STEP 1: Coordinator Agent - Plan what to ask each firm
        logger.info("[COORDINATOR] Planning phase...")
        step1_start = time.time()

        planning_response = anthropic_client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": f"""You are a coordinator agent. You received this question:
"{question}"

Available firms in our database: {', '.join(firms)}

For each firm, what specific question should we ask to fully answer the user's question?
Output ONE question per firm, in this format:
firm_name: [specific question to ask about that firm]

Example:
Bain: How many employees does Bain have?
CD&R: What is CD&R's employee count?

Generate for all {len(firms)} firms:"""
            }]
        )

        plan = planning_response.content[0].text
        step1_time = round((time.time() - step1_start) * 1000)
        pipeline_steps.append({
            "step": 1,
            "name": "Coordinator Planning",
            "duration_ms": step1_time,
            "details": f"Coordinator planned sub-queries for {len(firms)} firms",
            "plan": plan[:500]  # First 500 chars of plan
        })
        logger.info(f"[COORDINATOR] Plan:\n{plan}")

        # STEP 2: Sub-Agents - Each firm gets a specific query
        logger.info("[COORDINATOR] Executing sub-queries for each firm...")
        step2_start = time.time()
        firm_answers = {}
        sub_agent_details = []

        for firm in firms:
            logger.info(f"[SUB-AGENT] Querying {firm}...")
            sub_agent_start = time.time()

            # Create a firm-specific question based on the plan
            sub_question = f"{question} specifically for {firm}"

            # Query with this firm filter
            retrieval = self.retrieve(sub_question)
            chunks = retrieval.get("chunks", [])

            if chunks:
                # Let Claude extract the specific answer for this firm
                chunk_text = "\n".join([c["text"] for c in chunks[:3]])

                sub_response = anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=200,
                    messages=[{
                        "role": "user",
                        "content": f"""Based on this data about {firm}, answer: {question}

Data:
{chunk_text}

Provide a concise, specific answer about {firm} (1-2 sentences with numbers if available):"""
                    }]
                )

                answer = sub_response.content[0].text
                firm_answers[firm] = answer
                sub_time = round((time.time() - sub_agent_start) * 1000)
                sub_agent_details.append({
                    "firm": firm,
                    "chunks_found": len(chunks),
                    "duration_ms": sub_time,
                    "answer": answer[:150]
                })
                logger.info(f"[SUB-AGENT] {firm} answer: {answer[:100]}...")
            else:
                firm_answers[firm] = f"No data found for {firm}"
                sub_time = round((time.time() - sub_agent_start) * 1000)
                sub_agent_details.append({
                    "firm": firm,
                    "chunks_found": 0,
                    "duration_ms": sub_time,
                    "answer": "No data"
                })
                logger.info(f"[SUB-AGENT] {firm}: No data")

        step2_time = round((time.time() - step2_start) * 1000)
        pipeline_steps.append({
            "step": 2,
            "name": "Sub-Agents Execution",
            "duration_ms": step2_time,
            "details": f"Executed sub-agents for {len(firms)} firms, got {len([a for a in firm_answers.values() if 'No data' not in a])} responses",
            "sub_agents": sub_agent_details
        })

        # STEP 3: Coordinator Agent - Synthesize all firm answers
        logger.info("[COORDINATOR] Synthesis phase - comparing all firm answers...")
        step3_start = time.time()

        # Build comparison context from all firm answers
        all_answers = "\n".join([f"{firm}: {answer}" for firm, answer in firm_answers.items()])

        synthesis_response = anthropic_client.messages.create(
            model=self.model,
            max_tokens=512,
            system=[{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{
                "role": "user",
                "content": f"""You are a coordinator agent analyzing responses from sub-agents.

Original question: {question}

Responses from each firm's sub-agent:
{all_answers}

Now synthesize these responses to:
1. Identify which firm has the most/best/highest metric being asked about
2. Provide specific numbers when available
3. Explain the comparison clearly

Final answer:"""
            }]
        )

        final_answer = synthesis_response.content[0].text
        step3_time = round((time.time() - step3_start) * 1000)
        total_time = round((time.time() - start_time) * 1000)

        pipeline_steps.append({
            "step": 3,
            "name": "Coordinator Synthesis",
            "duration_ms": step3_time,
            "details": f"Coordinator synthesized responses from {len(firm_answers)} firms into final answer"
        })

        logger.info(f"[COORDINATOR] Complete in {total_time}ms")

        return {
            "question": question,
            "answer": final_answer,
            "chunk_count": len(firm_answers),
            "total_time_ms": total_time,
            "firms_analyzed": firms,
            "sub_agent_responses": firm_answers,
            "coordinator_plan": plan,
            "pipeline_details": pipeline_steps
        }


# Initialize pipeline
pipeline = RAGPipeline()


@app.route("/")
def index():
    """Serve frontend HTML"""
    return render_template("index.html")


@app.route("/api/debug", methods=["POST"])
def api_debug():
    """Debug endpoint to test POST requests"""
    print("[DEBUG] Endpoint hit!", flush=True)
    return jsonify({"status": "ok"})

@app.route("/api/query", methods=["POST"])
def api_query():
    """RAG query endpoint - uses agentic multi-step for complex questions"""
    try:
        print("[API] === QUERY ENDPOINT HIT ===", flush=True)
        data = request.json
        question = data.get("question", "").strip()
        print("[API] Question: {}".format(question), flush=True)

        if not question:
            return jsonify({"error": "Question cannot be empty"}), 400

        # Detect if question needs multi-step reasoning
        complex_keywords = ["which firm", "most", "least", "compare", "all firms", "ranking", "highest", "lowest"]
        is_complex = any(keyword in question.lower() for keyword in complex_keywords)
        print("[API] Is complex: {}".format(is_complex), flush=True)

        if is_complex:
            logger.info("Complex query detected - calling query_agentic()...")
            try:
                logger.info("Starting agentic query...")
                result = pipeline.query_agentic(question)
                logger.info("Agentic query completed")
            except Exception as e:
                logger.error(f"Agentic query failed: {e}", exc_info=True)
                logger.info("Falling back to standard query")
                result = pipeline.query(question)
        else:
            logger.info("Standard query - calling pipeline.query()...")
            result = pipeline.query(question)
            logger.info("Query completed")

        # Ensure result has required fields
        if not result:
            result = {"answer": "No answer generated", "error": "Empty result"}

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in query: {e}", exc_info=True)
        return jsonify({"error": str(e), "answer": "Error processing query"}), 500


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
