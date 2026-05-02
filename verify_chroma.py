from pathlib import Path
chroma_dir = Path('backend/chroma_data')
if chroma_dir.exists():
    files = list(chroma_dir.rglob('*'))
    print(f'ChromaDB persist dir exists: {chroma_dir}')
    print(f'Files inside: {len(files)}')
else:
    print('ERROR: chroma_data directory not found')