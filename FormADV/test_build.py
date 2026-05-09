#!/usr/bin/env python3
import os
from build_embeddings import chunk_pdf_text, build_embeddings

# Test chunking one PDF
chunks = chunk_pdf_text('Data/adv/CVC ADV.pdf')
print(f"Chunks created: {len(chunks)}")
print(f"First chunk length: {len(chunks[0]['text'].split())} tokens")
print(f"Estimated total tokens: {len(chunks) * 800}")

# Now test full build (this will use API credits)
print("\nStarting full build...")
success = build_embeddings()
print(f"Build success: {success}")
