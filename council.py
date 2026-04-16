import os
import sys

import chromadb
import ollama
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b")
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")

TOP_K = 8
ADVISORS = [
    {"collection": "ben_cowen", "name": "Ben Cowen"},
    {"collection": "lyn_alden", "name": "Lyn Alden"},
]

_ollama = ollama.Client(host=OLLAMA_BASE_URL)
_chroma = chromadb.PersistentClient(path=CHROMA_PATH)

ADVISOR_PROMPT_TEMPLATE = """You are responding as {creator_name}, the financial analyst and researcher.
Based ONLY on the following excerpts from their actual published content,
answer the user's question in their analytical style and voice.
Do not speculate beyond what is grounded in these excerpts.
If the excerpts do not adequately cover the question, say so clearly
rather than filling gaps with your own knowledge.

Excerpts (with dates for temporal context):
{retrieved_chunks_with_dates}

Question: {user_question}"""

SYNTHESIS_PROMPT_TEMPLATE = """The following are independent responses to a question from two financial analysts.
Summarise the council's view: identify where they agree, where they diverge,
and any tensions or complementary insights. Be direct and concrete.
Do not simply restate what each said — synthesise.

Question: {user_question}

Ben Cowen's view:
{ben_response}

Lyn Alden's view:
{lyn_response}"""


def _embed_question(question: str) -> list[float]:
    return _ollama.embeddings(model=EMBED_MODEL, prompt=question)["embedding"]


def _retrieve(collection_name: str, question_embedding: list[float]) -> list[tuple[str, dict]]:
    collection = _chroma.get_collection(collection_name)
    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=TOP_K,
        include=["documents", "metadatas"],
    )
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    return list(zip(docs, metas))


def _format_excerpts(chunks: list[tuple[str, dict]]) -> str:
    parts = []
    for doc, meta in chunks:
        date = meta.get("date", "")
        parts.append(f"[{date}]\n{doc}")
    return "\n\n---\n\n".join(parts)


def _unique_sources(chunks: list[tuple[str, dict]], limit: int = 3) -> list[dict]:
    seen = set()
    sources = []
    for _, meta in chunks:
        url = meta.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "title": meta.get("title", ""),
            "date": meta.get("date", ""),
            "url": url,
        })
        if len(sources) >= limit:
            break
    return sources


def _chat(prompt: str) -> str:
    response = _ollama.chat(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response["message"]["content"]


def query(question: str, verbose: bool = False) -> dict:
    def log(msg: str) -> None:
        if verbose:
            print(f"[council] {msg}", flush=True)

    log("Thinking...")
    log("Embedding question...")
    question_embedding = _embed_question(question)

    advisors = []
    for advisor in ADVISORS:
        log(f"Retrieving from {advisor['name']} (top {TOP_K})...")
        chunks = _retrieve(advisor["collection"], question_embedding)
        top_titles = ", ".join(s["title"] for s in _unique_sources(chunks))
        log(f"  top sources: {top_titles}")
        log(f"Generating {advisor['name']} response...")
        response = _chat(ADVISOR_PROMPT_TEMPLATE.format(
            creator_name=advisor["name"],
            retrieved_chunks_with_dates=_format_excerpts(chunks),
            user_question=question,
        ))
        advisors.append({
            "name": advisor["name"],
            "response": response,
            "sources": _unique_sources(chunks),
        })

    log("Synthesising council view...")
    synthesis = _chat(SYNTHESIS_PROMPT_TEMPLATE.format(
        user_question=question,
        ben_response=advisors[0]["response"],
        lyn_response=advisors[1]["response"],
    ))
    log("Done.")

    return {
        "question": question,
        "advisors": advisors,
        "synthesis": synthesis,
    }


def _print_result(result: dict) -> None:
    print(f"\n=== Question ===\n{result['question']}\n")
    for advisor in result["advisors"]:
        print(f"=== {advisor['name']} ===")
        print(advisor["response"])
        if advisor["sources"]:
            print("\nSources:")
            for src in advisor["sources"]:
                print(f"  - {src['title']} ({src['date']})\n    {src['url']}")
        print()
    print("=== Synthesis ===")
    print(result["synthesis"])
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python council.py "<question>"')
        sys.exit(1)
    _print_result(query(sys.argv[1], verbose=True))
