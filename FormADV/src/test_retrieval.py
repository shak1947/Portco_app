"""
Sanity test for retrieval.
Loads the persisted Chroma index and runs 3 test queries.
"""

import sys
from pathlib import Path
import logging

from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Test queries
TEST_QUERIES = [
    "management fee structure",
    "conflicts of interest",
    "valuation policy",
]


def test_retrieval(chroma_path: str = "data/chroma", top_k: int = 5) -> None:
    """Load Chroma index and run test queries."""

    chroma_path = Path(chroma_path)
    if not chroma_path.exists():
        logger.error(f"Chroma vector store not found at {chroma_path}")
        logger.error("Run 'python src/ingest.py' first to build the index.")
        sys.exit(1)

    logger.info(f"Loading vector store from {chroma_path}...")
    client = chromadb.PersistentClient(path=str(chroma_path))

    try:
        collection = client.get_collection(name="form_adv")
    except ValueError:
        logger.error("Collection 'form_adv' not found in vector store")
        sys.exit(1)

    # Initialize embedder
    logger.info("Loading embedding model BAAI/bge-small-en-v1.5...")
    embedder = HuggingFaceEmbedding(
        model_name="BAAI/bge-small-en-v1.5",
        cache_folder="./.cache"
    )

    logger.info(f"Vector store loaded with {collection.count()} chunks\n")

    # Run test queries
    for query in TEST_QUERIES:
        logger.info(f"Query: '{query}'")
        logger.info("-" * 80)

        # Embed the query
        query_embedding = embedder.get_text_embedding(query)

        # Query the collection
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )

        if not results["ids"] or not results["ids"][0]:
            logger.info("No results found.\n")
            continue

        # Display results
        for i, (doc_id, distance, metadata) in enumerate(
            zip(results["ids"][0], results["distances"][0], results["metadatas"][0])
        ):
            # Chroma returns distances; similarity = 1 - distance for cosine
            similarity = 1 - distance
            firm_name = metadata.get("firm_name", "Unknown")
            page_num = metadata.get("page_number", "Unknown")
            source_file = metadata.get("source_file", "Unknown")

            # Get the actual document text
            doc_text = results["documents"][0][i]
            preview = doc_text[:200].replace("\n", " ")

            print(f"  [{i+1}] Similarity: {similarity:.4f}")
            print(f"      Firm: {firm_name} | Page: {page_num} | File: {source_file}")
            print(f"      Preview: {preview}...")
            print()

        print()


if __name__ == "__main__":
    test_retrieval()
