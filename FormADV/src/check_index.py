"""
Diagnostic script to check what's actually indexed in Chroma.
"""

import sys
from pathlib import Path
from collections import Counter
import chromadb

chroma_path = Path("data/chroma")
if not chroma_path.exists():
    print("Chroma vector store not found")
    sys.exit(1)

client = chromadb.PersistentClient(path=str(chroma_path))
try:
    collection = client.get_collection(name="form_adv")
except ValueError:
    print("Collection 'form_adv' not found")
    sys.exit(1)

# Get all metadata
total_chunks = collection.count()
print(f"Total chunks in vector store: {total_chunks}\n")

# Get all entries (Chroma doesn't have a direct "get all" but we can query with a high n_results)
all_results = collection.get()

if all_results["metadatas"]:
    firm_counts = Counter([m["firm_name"] for m in all_results["metadatas"]])
    file_counts = Counter([m["source_file"] for m in all_results["metadatas"]])

    print("Chunks per firm:")
    for firm, count in sorted(firm_counts.items(), key=lambda x: -x[1]):
        print(f"  {firm}: {count} chunks")

    print("\nChunks per file:")
    for file, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        print(f"  {file}: {count} chunks")

    print(f"\nUnique firms: {len(firm_counts)}")
    print(f"Unique files: {len(file_counts)}")
else:
    print("No metadata found in collection")
