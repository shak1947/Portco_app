"""
Phase 2: Claude-powered query synthesis.
Retrieves relevant Form ADV excerpts and generates grounded answers with citations.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
import logging

import chromadb
from anthropic import Anthropic
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class Source:
    """Citation metadata for a retrieved chunk."""
    firm_name: str
    page_number: str
    source_file: str
    similarity: float
    excerpt: str


@dataclass
class QueryResult:
    """Structured result from a query."""
    question: str
    answer: str
    sources: list[Source]


def ask(
    question: str,
    top_k: int = 5,
    chroma_path: str = "data/chroma",
    model: str = "claude-sonnet-4-6"
) -> QueryResult:
    """
    Answer a question about Form ADV documents using Claude.

    Args:
        question: The user's question
        top_k: Number of top chunks to retrieve
        chroma_path: Path to Chroma vector store
        model: Claude model to use

    Returns:
        QueryResult with answer and sources
    """

    chroma_path = Path(chroma_path)
    if not chroma_path.exists():
        logger.error(f"Chroma vector store not found at {chroma_path}")
        logger.error("Run 'python src/ingest.py' first to build the index.")
        sys.exit(1)

    # Load vector store
    logger.info("Loading vector store...")
    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        collection = client.get_collection(name="form_adv")
    except ValueError:
        logger.error("Collection 'form_adv' not found in vector store")
        sys.exit(1)

    # Initialize OpenAI embedder
    logger.info("Loading OpenAI embedding model...")
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Retrieve relevant chunks
    logger.info(f"Retrieving top {top_k} chunks for query...")
    embedding_response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    )
    query_embedding = embedding_response.data[0].embedding
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    # Build sources and context
    sources = []
    context_parts = []

    if results["ids"] and results["ids"][0]:
        for i, (doc_id, distance, metadata, doc_text) in enumerate(
            zip(
                results["ids"][0],
                results["distances"][0],
                results["metadatas"][0],
                results["documents"][0]
            )
        ):
            similarity = 1 - distance
            firm_name = metadata.get("firm_name", "Unknown")
            page_num = metadata.get("page_number", "Unknown")
            source_file = metadata.get("source_file", "Unknown")
            excerpt = doc_text[:200].replace("\n", " ")

            sources.append(
                Source(
                    firm_name=firm_name,
                    page_number=page_num,
                    source_file=source_file,
                    similarity=similarity,
                    excerpt=excerpt
                )
            )

            # Build context string for Claude
            context_parts.append(
                f"[Source {i+1}] {firm_name} | Page {page_num}\n{doc_text}"
            )

    context = "\n\n".join(context_parts)

    # Call Claude with prompt caching
    logger.info("Calling Claude...")
    anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = anthropic.messages.create(
        model=model,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": """You are a PE due diligence analyst with access to Form ADV documents from exactly 10 firms:
1. Bain & Company
2. Clayton Dubilier & Rice
3. CVC Capital Partners
4. EQT Partners
5. Hellman & Friedman
6. Kelso & Company
7. TA Associates
8. Thoma Bravo
9. Visa Inc.
10. Warburg Pincus

For specific questions about firm practices, answer based only on the excerpts provided. Always cite sources.

CRITICAL RULE: If asked about how many companies/firms are in the dataset, or what firms are available, ALWAYS respond with the complete list of 10 firms above, regardless of what excerpts are shown.""",
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Form ADV Excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"
            }
        ]
    )

    answer = response.content[0].text

    logger.info("Query complete.")
    return QueryResult(question=question, answer=answer, sources=sources)


def print_result(result: QueryResult) -> None:
    """Pretty-print a QueryResult to stdout."""
    print(f"\nQuestion: {result.question}\n")
    print("Answer:")
    print(result.answer)
    print("\nSources:")
    for i, source in enumerate(result.sources, 1):
        print(
            f"  [{i}] {source.firm_name} | Page {source.page_number} | "
            f"Similarity: {source.similarity:.3f}"
        )
        print(f"      {source.excerpt}...")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/query.py \"Your question here\"")
        sys.exit(1)

    question = sys.argv[1]
    result = ask(question)
    print_result(result)
