"""
Resumable chunking and embedding pipeline with graph storage.
Saves progress after each PDF so failed runs can resume.
"""
import os
import json
import logging
import time
from pathlib import Path
from dotenv import load_dotenv
import duckdb
import chromadb
import pdfplumber
from openai import OpenAI, RateLimitError
from llama_index.core.text_splitter import SentenceSplitter
import tiktoken

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
encoding = tiktoken.encoding_for_model("gpt-4")

FIRM_MAPPING = {
    "Bain ADV.pdf": "Bain & Company",
    "CD&R Form ADV.pdf": "Clayton Dubilier & Rice",
    "CVC ADV.pdf": "CVC Capital Partners",
    "EQT ADV.pdf": "EQT Partners",
    "Hellman ADV.pdf": "Hellman & Friedman",
    "Kelso ADV.pdf": "Kelso & Company",
    "TA Associate ADV.pdf": "TA Associates",
    "Thoma ADV.pdf": "Thoma Bravo",
    "Visa ADV.pdf": "Visa Inc.",
    "Warburg Form ADV.pdf": "Warburg Pincus",
}

class ResumablePipeline:
    def __init__(self, data_dir="Data/adv", db_path="Data/graph.duckdb",
                 chroma_path="Data/chroma_openai", progress_file="Data/progress.json"):
        self.data_dir = Path(data_dir)
        self.db_path = db_path
        self.chroma_path = Path(chroma_path)
        self.progress_file = Path(progress_file)

        # Initialize DuckDB
        self.db = duckdb.connect(self.db_path, read_only=False)
        self._init_db()

        # Initialize Chroma
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(path=str(self.chroma_path))
        try:
            self.chroma_client.delete_collection(name="form_adv")
        except:
            pass
        self.collection = self.chroma_client.create_collection(
            name="form_adv",
            metadata={"hnsw:space": "cosine"}
        )

        self.splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)

        # Load progress
        self.progress = self._load_progress()

    def _init_db(self):
        """Initialize DuckDB tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id VARCHAR PRIMARY KEY,
                firm_name VARCHAR,
                source_file VARCHAR,
                total_pages INTEGER,
                total_chunks INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id VARCHAR PRIMARY KEY,
                doc_id VARCHAR,
                chunk_index INTEGER,
                page_number INTEGER,
                content TEXT,
                token_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                chunk_id VARCHAR PRIMARY KEY,
                embedding FLOAT8[],
                embedding_model VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS chunk_relationships (
                source_chunk_id VARCHAR,
                target_chunk_id VARCHAR,
                relationship_type VARCHAR,
                similarity_score FLOAT,
                PRIMARY KEY (source_chunk_id, target_chunk_id, relationship_type),
                FOREIGN KEY (source_chunk_id) REFERENCES chunks(chunk_id),
                FOREIGN KEY (target_chunk_id) REFERENCES chunks(chunk_id)
            )
        """)

    def _load_progress(self) -> dict:
        """Load progress from file."""
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {"processed_files": [], "total_chunks": 0}

    def _save_progress(self):
        """Save progress to file."""
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def extract_pdf_text(self, pdf_path: Path) -> dict:
        """Extract text from PDF."""
        text_by_page = {}
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        text_by_page[page_num] = text
        except Exception as e:
            logger.error(f"Failed to extract from {pdf_path}: {e}")
            raise
        return text_by_page

    def count_tokens(self, text: str) -> int:
        """Count tokens."""
        return len(encoding.encode(text))

    def chunk_text(self, text: str) -> list:
        """Chunk text."""
        chunks = self.splitter.split_text(text)
        validated = []
        for chunk in chunks:
            token_count = self.count_tokens(chunk)
            if token_count > 2000:
                subchunks = self.splitter.split_text(chunk, chunk_size=500, chunk_overlap=50)
                validated.extend(subchunks)
            else:
                validated.append(chunk)
        return validated

    def embed_chunks(self, chunks: list) -> list:
        """Embed chunks with rate limit handling."""
        embeddings = []
        batch_size = 75  # Increased for speed

        logger.info(f"Embedding {len(chunks)} chunks...")

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(chunks) + batch_size - 1) // batch_size

            logger.info(f"  Batch {batch_num}/{total_batches}...")

            for attempt in range(5):
                try:
                    response = client.embeddings.create(
                        model="text-embedding-3-small",
                        input=batch
                    )
                    embeddings.extend([item.embedding for item in response.data])
                    time.sleep(0.5)  # Faster rate limiting
                    break
                except RateLimitError as e:
                    if attempt < 4:
                        wait = 2 ** attempt
                        logger.warning(f"    Rate limited. Waiting {wait}s...")
                        time.sleep(wait)
                    else:
                        raise

        return embeddings

    def process_pdf(self, pdf_path: Path) -> int:
        """Process one PDF."""
        if pdf_path.name in self.progress["processed_files"]:
            logger.info(f"Skipping {pdf_path.name} (already processed)")
            return 0

        logger.info(f"\nProcessing {pdf_path.name}...")

        firm_name = FIRM_MAPPING.get(pdf_path.name, pdf_path.stem)
        doc_id = pdf_path.stem.lower().replace(" ", "_")

        # Extract
        text_by_page = self.extract_pdf_text(pdf_path)
        if not text_by_page:
            logger.warning(f"No text from {pdf_path.name}")
            return 0

        logger.info(f"  {len(text_by_page)} pages")

        # Chunk
        full_text = "\n\n".join([f"[Page {pn}]\n{txt}" for pn, txt in text_by_page.items()])
        chunks = self.chunk_text(full_text)
        logger.info(f"  {len(chunks)} chunks")

        # Prepare
        chunk_ids = []
        chunk_contents = []
        token_counts = []
        chunk_page_nums = []

        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{chunk_idx}"
            chunk_ids.append(chunk_id)
            chunk_contents.append(chunk)
            token_counts.append(self.count_tokens(chunk))

            page_num = 1
            for pn in sorted(text_by_page.keys()):
                if f"[Page {pn}]" in chunk:
                    page_num = pn
            chunk_page_nums.append(page_num)

        # Embed
        embeddings = self.embed_chunks(chunk_contents)

        # Store in DuckDB
        self.db.execute(
            "INSERT OR IGNORE INTO documents (doc_id, firm_name, source_file, total_pages, total_chunks) VALUES (?, ?, ?, ?, ?)",
            [doc_id, firm_name, pdf_path.name, len(text_by_page), len(chunks)]
        )

        for chunk_id, content, token_count, page_num in zip(
            chunk_ids, chunk_contents, token_counts, chunk_page_nums
        ):
            self.db.execute(
                "INSERT OR IGNORE INTO chunks (chunk_id, doc_id, chunk_index, page_number, content, token_count) VALUES (?, ?, ?, ?, ?, ?)",
                [chunk_id, doc_id, chunk_ids.index(chunk_id), page_num, content, token_count]
            )

        for chunk_id, embedding in zip(chunk_ids, embeddings):
            self.db.execute(
                "INSERT OR IGNORE INTO embeddings (chunk_id, embedding, embedding_model) VALUES (?, ?, ?)",
                [chunk_id, embedding, "text-embedding-3-small"]
            )

        # Store in Chroma
        metadatas = [
            {
                "firm_name": firm_name,
                "page_number": str(page_num),
                "source_file": pdf_path.name,
                "chunk_index": str(idx)
            }
            for idx, page_num in enumerate(chunk_page_nums)
        ]

        self.collection.add(
            ids=chunk_ids,
            documents=chunk_contents,
            embeddings=embeddings,
            metadatas=metadatas
        )

        # Build relationships
        for i in range(len(chunk_ids) - 1):
            self.db.execute(
                "INSERT OR IGNORE INTO chunk_relationships (source_chunk_id, target_chunk_id, relationship_type) VALUES (?, ?, ?)",
                [chunk_ids[i], chunk_ids[i+1], "consecutive"]
            )

        self.db.commit()

        # Update progress
        self.progress["processed_files"].append(pdf_path.name)
        self.progress["total_chunks"] += len(chunks)
        self._save_progress()

        logger.info(f"  ✓ {firm_name}: {len(chunks)} chunks")
        return len(chunks)

    def run(self):
        """Process all PDFs."""
        pdf_files = sorted(self.data_dir.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDFs")

        for pdf_file in pdf_files:
            try:
                self.process_pdf(pdf_file)
            except Exception as e:
                logger.error(f"FAILED {pdf_file.name}: {e}")
                self.db.commit()
                self._save_progress()
                raise

        self.db.commit()
        logger.info(f"\n{'='*60}")
        logger.info(f"Complete! Total chunks: {self.progress['total_chunks']}")
        logger.info(f"Processed files: {len(self.progress['processed_files'])}")
        logger.info(f"{'='*60}")

if __name__ == "__main__":
    pipeline = ResumablePipeline()
    pipeline.run()
