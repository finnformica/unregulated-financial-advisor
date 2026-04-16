import json
import os
from datetime import datetime
from pathlib import Path

import chromadb
import frontmatter
import ollama
from dotenv import load_dotenv

SOURCES = {
    "files/lyn_alden_blog": "lyn_alden",
    "files/ben_cowen_youtube": "ben_cowen",
}
CHUNK_SIZE_WORDS = 500
CHUNK_OVERLAP_WORDS = 50
STATE_PATH = "ingest_state.json"
METADATA_KEYS = ("creator", "date", "title", "url", "source")


def load_ingest_state() -> dict:
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_ingest_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=4)


def chunk_text(
    body: str, size: int = CHUNK_SIZE_WORDS, overlap: int = CHUNK_OVERLAP_WORDS
) -> list[str]:
    words = body.split()
    if not words:
        return []

    chunks = []
    stride = size - overlap
    for start in range(0, len(words), stride):
        window = words[start : start + size]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + size >= len(words):
            break
    return chunks


def embed_chunk(client: ollama.Client, model: str, text: str) -> list[float]:
    response = client.embeddings(model=model, prompt=text)
    return response["embedding"]


def process_file(
    path: Path,
    collection,
    ollama_client: ollama.Client,
    embed_model: str,
) -> int:
    post = frontmatter.load(path)
    meta = {key: str(post.metadata.get(key) or "") for key in METADATA_KEYS}
    meta["file_path"] = str(path)

    chunks = chunk_text(post.content)
    if not chunks:
        return 0

    ids, embeddings, documents, metadatas = [], [], [], []
    for i, chunk in enumerate(chunks):
        ids.append(f"{path}#{i}")
        embeddings.append(embed_chunk(ollama_client, embed_model, chunk))
        documents.append(chunk)
        metadatas.append({**meta, "chunk_index": i})

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    return len(chunks)


def main() -> None:
    load_dotenv()
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    chroma_path = os.getenv("CHROMA_PATH", "./chroma_db")

    ollama_client = ollama.Client(host=ollama_base_url)
    chroma_client = chromadb.PersistentClient(path=chroma_path)

    state = load_ingest_state()
    files_processed = 0
    files_skipped = 0
    chunks_upserted = 0

    try:
        for src_dir, collection_name in SOURCES.items():
            src_path = Path(src_dir)
            if not src_path.is_dir():
                print(f"[ingest] skip: {src_dir} does not exist")
                continue

            collection = chroma_client.get_or_create_collection(name=collection_name)
            md_files = sorted(src_path.glob("*.md"))
            total = len(md_files)
            print(f"[ingest] {src_dir} -> {collection_name} ({total} files)")

            for i, path in enumerate(md_files, 1):
                key = str(path)
                if key in state:
                    files_skipped += 1
                    continue

                n = process_file(path, collection, ollama_client, embed_model)
                state[key] = datetime.now().isoformat()
                save_ingest_state(state)
                files_processed += 1
                chunks_upserted += n
                print(f"[ingest]   ({i}/{total}) {path.name} -> {n} chunks")
    finally:
        save_ingest_state(state)

    print("[ingest] done")
    print(f"  files processed: {files_processed}")
    print(f"  files skipped:   {files_skipped}")
    print(f"  chunks upserted: {chunks_upserted}")
    print(f"  collections:     {', '.join(SOURCES.values())}")


if __name__ == "__main__":
    main()
