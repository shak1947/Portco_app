import sys
from pathlib import Path
import logging
import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

def ingest_single_pdf(pdf_filename, data_dir="data/adv", chroma_path="data/chroma"):
    pdf_path = Path(data_dir) / pdf_filename
    if not pdf_path.exists():
        logger.error(f"PDF not found: {pdf_path}")
        return
    
    logger.info(f"Processing {pdf_filename}...")
    firm_name = FIRM_MAPPING.get(pdf_filename, pdf_path.stem)
    
    # Extract text
    text_by_page = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                text_by_page[page_num] = text
    
    logger.info(f"Extracted {len(text_by_page)} pages")
    
    # Load embedder and splitter
    embedder = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_folder="./.cache")
    splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)
    
    # Load or create Chroma
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    
    try:
        collection = client.get_collection(name="form_adv")
        logger.info("Using existing collection")
    except ValueError:
        collection = client.create_collection(name="form_adv", metadata={"hnsw:space": "cosine"})
        logger.info("Created new collection")
    
    # Chunk and embed
    full_text = "\n\n".join([f"[Page {pn}]\n{txt}" for pn, txt in text_by_page.items()])
    chunks = splitter.split_text(full_text)
    logger.info(f"Created {len(chunks)} chunks")
    
    for idx, chunk in enumerate(chunks):
        page_num = 1
        for pn in sorted(text_by_page.keys()):
            if f"[Page {pn}]" in chunk:
                page_num = pn
        
        embedding = embedder.get_text_embedding(chunk)
        collection.add(
            ids=[f"{pdf_path.stem}_chunk_{idx}"],
            documents=[chunk],
            embeddings=[embedding],
            metadatas=[{
                "firm_name": firm_name,
                "page_number": str(page_num),
                "source_file": pdf_filename,
                "chunk_index": str(idx)
            }]
        )
    
    logger.info(f"✓ Indexed {len(chunks)} chunks from {firm_name}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ingest_single_pdf(sys.argv[1])
    else:
        print("Usage: python src/ingest_single.py <pdf_filename>")
