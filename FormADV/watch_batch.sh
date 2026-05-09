#!/bin/bash
echo "Batch Ingestion Monitor"
echo "======================="
while true; do
  python -c "
import chromadb
from collections import Counter
import sys
try:
    c = chromadb.PersistentClient('data/chroma_fresh')
    coll = c.get_collection('form_adv')
    total = coll.count()
    if total > 0:
        meta = coll.get()
        firms = Counter([m['firm_name'] for m in meta['metadatas']])
        print(f'✓ Total chunks: {total}')
        for firm in sorted(firms.keys()):
            print(f'  {firm}: {firms[firm]} chunks')
    else:
        print('⏳ Still embedding first PDF...')
except Exception as e:
    print(f'⏳ Initializing... ({str(e)[:50]})')
" 2>&1
  sleep 30
done
