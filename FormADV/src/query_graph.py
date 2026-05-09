"""
Query the graph database and vector store for embedded chunks.
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv
import duckdb
import chromadb

load_dotenv()

class GraphQueryEngine:
    def __init__(self, db_path: str = "Data/graph.duckdb", chroma_path: str = "Data/chroma_openai"):
        self.db = duckdb.connect(db_path)
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = self.chroma_client.get_collection(name="form_adv")

    def vector_search(self, query: str, top_k: int = 5) -> list:
        """Search using vector similarity in Chroma."""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )

        chunks = []
        if results and results['documents']:
            for doc, metadata, distance in zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            ):
                chunks.append({
                    'content': doc,
                    'firm_name': metadata['firm_name'],
                    'page': metadata['page_number'],
                    'source': metadata['source_file'],
                    'similarity': 1 - distance  # Convert distance to similarity
                })

        return chunks

    def get_chunk_context(self, chunk_id: str) -> dict:
        """Get a chunk and its neighbors in the graph."""
        chunk = self.db.execute(
            "SELECT chunk_id, content, doc_id, page_number FROM chunks WHERE chunk_id = ?",
            [chunk_id]
        ).fetchall()

        if not chunk:
            return None

        chunk_data = chunk[0]

        # Get neighboring chunks
        neighbors = self.db.execute("""
            SELECT target_chunk_id FROM chunk_relationships
            WHERE source_chunk_id = ? AND relationship_type = 'consecutive'
        """, [chunk_id]).fetchall()

        return {
            'chunk_id': chunk_data[0],
            'content': chunk_data[1],
            'doc_id': chunk_data[2],
            'page': chunk_data[3],
            'next_chunks': [n[0] for n in neighbors]
        }

    def search_by_firm(self, firm_name: str) -> dict:
        """Get all chunks for a specific firm."""
        docs = self.db.execute(
            "SELECT doc_id FROM documents WHERE firm_name = ?",
            [firm_name]
        ).fetchall()

        if not docs:
            return None

        doc_id = docs[0][0]
        chunks = self.db.execute(
            "SELECT chunk_id, content, page_number FROM chunks WHERE doc_id = ? ORDER BY chunk_index",
            [doc_id]
        ).fetchall()

        return {
            'firm_name': firm_name,
            'chunk_count': len(chunks),
            'chunks': [
                {
                    'id': c[0],
                    'content': c[1][:200] + '...' if len(c[1]) > 200 else c[1],
                    'page': c[2]
                }
                for c in chunks[:10]  # First 10
            ]
        }

    def get_firms(self) -> list:
        """List all firms in the database."""
        firms = self.db.execute(
            "SELECT firm_name, total_chunks FROM documents ORDER BY total_chunks DESC"
        ).fetchall()
        return [{'firm': f[0], 'chunks': f[1]} for f in firms]

    def search_firms(self, query: str) -> list:
        """Search across all firms."""
        firms = self.get_firms()
        results = {}

        for firm in firms:
            firm_name = firm['firm']
            firm_chunks = self.db.execute(
                "SELECT doc_id FROM documents WHERE firm_name = ?",
                [firm_name]
            ).fetchall()

            if firm_chunks:
                doc_id = firm_chunks[0][0]
                matching_chunks = self.db.execute(
                    "SELECT chunk_id, content FROM chunks WHERE doc_id = ? LIMIT 3",
                    [doc_id]
                ).fetchall()

                results[firm_name] = {
                    'total_chunks': firm['chunks'],
                    'sample': [{'id': c[0], 'preview': c[1][:150]} for c in matching_chunks]
                }

        return results

if __name__ == "__main__":
    engine = GraphQueryEngine()

    # List all firms
    print("Firms in database:")
    for firm in engine.get_firms():
        print(f"  {firm['firm']}: {firm['chunks']} chunks")

    # Example vector search
    print("\n\nExample search: 'investment strategy'")
    results = engine.vector_search("investment strategy", top_k=3)
    for r in results:
        print(f"  [{r['firm_name']}] {r['content'][:100]}...")
