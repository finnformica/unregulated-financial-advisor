# Council of Advisors — Master Plan

## Project Overview

A fully local, private financial research assistant running on a Mac Mini on the home network. Scrapes content from two financial creators on a schedule, indexes it into a per-creator vector store, and answers questions by generating a grounded response from each creator in their own voice followed by a synthesised council summary. No external API costs. Accessible from any device on the home network via a private web UI.

### Current state

- **Built:** `scrapers/youtube.py`, `scrapers/lyn_alden_blog.py`, `scrapers/utils.py`, `scrape.py`, `last_synced.json`, populated `files/` corpus (~715 markdown files).
- **Not yet built:** `ingest.py`, `council.py`, `app.py`, `sync.sh`, `templates/`, `static/`, `com.council.sync.plist`, `README.md`, `.env.example`, expanded `requirements.txt`, expanded `.gitignore`.

---

## Repository Structure

```
/council
├── scrapers/                       ← (existing)
│   ├── youtube.py                  ← Ben Cowen YouTube scraper (existing)
│   ├── lyn_alden_blog.py           ← Lyn Alden blog scraper (existing)
│   └── utils.py                    ← shared frontmatter/state helpers (existing)
│
├── files/                          ← (existing) scraped markdown files, organised by scraper_name
│   ├── ben_cowen_youtube/          ← ~530 files, format: "{title} ({YYYY-MM-DD}).md"
│   └── lyn_alden_blog/             ← ~185 files, format: "{title}.md" (date prefix in title)
│
├── ingest.py                       ← chunks, embeds, upserts into ChromaDB (planned)
├── council.py                      ← core RAG + advisor + synthesis logic (planned)
├── app.py                          ← FastAPI web server (planned)
├── scrape.py                         ← scraper entrypoint (existing)
├── sync.sh                         ← orchestrates scrape → ingest → git push (planned)
│
├── templates/
│   └── index.html                  ← chat UI (Jinja2, planned)
│
├── static/
│   └── style.css                   ← (planned)
│
├── last_synced.json                ← (existing) tracks last scraped date per scraper_name (root-level)
├── ingest_state.json               ← (planned) tracks which files have been embedded (root-level)
│
├── .env                            ← credentials (gitignored, existing)
├── .gitignore                      ← (existing)
├── requirements.txt                ← (existing, needs expansion)
├── venv/                           ← virtualenv (existing, gitignored)
├── README.md                       ← (planned)
└── com.council.sync.plist          ← launchd schedule config (macOS, planned)
```

**Note on state files:** existing code (`scrapers/utils.py`) reads/writes `last_synced.json` at the project root. To stay consistent, `ingest_state.json` will also live at the root rather than under a `state/` directory.

---

## Creators & Content

| Creator   | Source                        | Scraper                                                | scraper_name         | Volume    |
| --------- | ----------------------------- | ------------------------------------------------------ | -------------------- | --------- |
| Ben Cowen | YouTube (@intothecryptoverse) | YouTube Data API v3 + youtube-transcript-api           | `ben_cowen_youtube`  | ~530 files |
| Lyn Alden | Paid blog (lynalden.com)      | Playwright (authenticated session) + markdownify       | `lyn_alden_blog`     | ~185 files |

Total current corpus: ~715 markdown files.

The `scraper_name` is the subdirectory name under `files/` and the key used in `last_synced.json`. For YouTube it is derived from `{creator.lower().replace(' ', '_')}_youtube`; for the Lyn Alden blog it is hardcoded to `lyn_alden_blog`.

### Frontmatter schema (existing, must be preserved)

Written by `scrapers/utils.py::write_markdown` using `python-frontmatter`. All values stored as strings (the `date` value is stringified via `str(date)` before write).

```yaml
---
title: Jobs Report
url: https://www.youtube.com/watch?v=1TWdVGIKqu0
creator: Ben Cowen        # or "Lyn Alden"
source: youtube           # or "blog"
date: '2024-02-02 19:43:19+00:00'   # youtube: datetime; blog: ISO date string
---
```

---

## Stack

| Concern         | Choice                      | Notes                                         |
| --------------- | --------------------------- | --------------------------------------------- |
| Model server    | Ollama                      | Runs as background service on Mac Mini        |
| Embedding model | nomic-embed-text            | Via Ollama, free, local                       |
| Chat model      | llama3.1:8b or llama3.1:70b | Decided once RAM is confirmed                 |
| Vector store    | ChromaDB (persistent)       | Per-creator collections, no separate service  |
| Web framework   | FastAPI + Jinja2            | Bound to 0.0.0.0, accessible on local network |
| Auth            | HTTP Basic Auth middleware  | Single user, credentials in .env              |
| Scheduler       | launchd (macOS native)      | More reliable than cron on Mac                |
| Git remote      | Private GitHub repo         | SSH key auth from Mac Mini                    |

---

## Component Specifications

### 1. `ingest.py`

**Purpose:** Reads all markdown files in `content/`, chunks them, embeds via Ollama, and upserts into ChromaDB. Incremental — tracks ingested files in `state/ingest_state.json` so reruns only process new files.

**Behaviour:**

- Walk `files/ben_cowen_youtube/` and `files/lyn_alden_blog/` separately
- Parse YAML frontmatter (via `python-frontmatter`) to extract `creator`, `date`, `title`, `url`, `source`
- Strip frontmatter, chunk body text at ~500 tokens with 50-token overlap
- Embed each chunk using `nomic-embed-text` via Ollama
- Upsert into ChromaDB with two collections: `ben_cowen` and `lyn_alden` (collection names normalised from creator)
- Store metadata per chunk: `creator`, `date`, `title`, `url`, `source`, `chunk_index`, `file_path`
- On completion, write processed file paths + timestamps to `ingest_state.json` (root-level)
- Log new files ingested, skip already-ingested files

**Key decisions:**

- Chunk size 500 tokens balances retrieval precision against context loss for long transcripts
- Upsert (not insert) ensures reruns are safe and idempotent
- ChromaDB persistent mode — data survives restarts

---

### 2. `council.py`

**Purpose:** Core RAG logic. Given a user question, retrieves relevant chunks per creator, generates an advisor response per creator, then generates a synthesis.

**Query flow:**

```
user_question
     │
     ├── ChromaDB query → ben_cowen collection → top 8 chunks
     │        └── Ollama chat call (Ben Cowen persona prompt + chunks)
     │                  └── ben_response
     │
     ├── ChromaDB query → lyn_alden collection → top 8 chunks
     │        └── Ollama chat call (Lyn Alden persona prompt + chunks)
     │                  └── lyn_response
     │
     └── Ollama chat call (synthesis prompt + both responses)
               └── synthesis
```

**Advisor persona prompt template:**

```
You are responding as {creator_name}, the financial analyst and researcher.
Based ONLY on the following excerpts from their actual published content,
answer the user's question in their analytical style and voice.
Do not speculate beyond what is grounded in these excerpts.
If the excerpts do not adequately cover the question, say so clearly
rather than filling gaps with your own knowledge.

Excerpts (with dates for temporal context):
{retrieved_chunks_with_dates}

Question: {user_question}
```

**Synthesis prompt template:**

```
The following are independent responses to a question from two financial analysts.
Summarise the council's view: identify where they agree, where they diverge,
and any tensions or complementary insights. Be direct and concrete.
Do not simply restate what each said — synthesise.

Question: {user_question}

Ben Cowen's view:
{ben_response}

Lyn Alden's view:
{lyn_response}
```

**Return structure:**

```python
{
    "question": str,
    "advisors": [
        {
            "name": "Ben Cowen",
            "response": str,
            "sources": [{"title": str, "date": str, "url": str}]  # top 3
        },
        {
            "name": "Lyn Alden",
            "response": str,
            "sources": [{"title": str, "date": str, "url": str}]
        }
    ],
    "synthesis": str
}
```

**Configuration:**

- `top_k = 8` chunks retrieved per creator (tunable)
- Ollama base URL: `http://localhost:11434`
- ChromaDB path: `./chroma_db`

---

### 3. `app.py`

**Purpose:** FastAPI server exposing the council to the local network via a browser UI.

**Routes:**

- `GET /` — serves `templates/index.html` (chat UI)
- `POST /query` — accepts `{"question": str}`, calls `council.py`, returns full council response as JSON
- `GET /health` — returns `{"status": "ok"}`, used to check server is running

**Auth:**

- HTTP Basic Auth middleware on all routes
- Credentials loaded from `.env`: `COUNCIL_USER`, `COUNCIL_PASSWORD`

**Server config:**

- Bound to `0.0.0.0:8000` so accessible from any device on the home network
- Run via `uvicorn app:app --host 0.0.0.0 --port 8000`

**UI behaviour (`index.html`):**

- Single page chat interface
- User types a question, submits
- Shows a loading state while the three LLM calls complete (this will take 30–90 seconds on local hardware)
- Renders advisor responses in clearly labelled sections, each with their source links
- Renders synthesis section below
- Retains conversation history in the page session (not persisted)
- Minimal, functional design — dark background, monospace or editorial font, clear section delineation

---

### 4. `sync.sh`

**Purpose:** Orchestrates the full weekly pipeline — scrape, ingest, git push.

```bash
#!/bin/bash
set -e

cd /path/to/council

# Activate virtual environment (existing dir is `venv/`, not `.venv/`)
source venv/bin/activate

# Run scrapers
echo "[sync] Running scrapers..."
python scrape.py

# Run ingestion
echo "[sync] Running ingestion..."
python ingest.py

# Git: commit and push if there are new files
if [[ -n $(git status --porcelain files/) ]]; then
    echo "[sync] New content found, committing..."
    git add files/ last_synced.json ingest_state.json
    git commit -m "sync: $(date '+%Y-%m-%d') automated content update"
    git push origin main
    echo "[sync] Pushed to remote."
else
    echo "[sync] No new content."
fi

echo "[sync] Done."
```

---

### 5. `com.council.sync.plist` (launchd)

**Purpose:** macOS-native scheduler. Runs `sync.sh` on a schedule without needing cron.

**Schedule:** Every 3 days at 03:00.

**Key config:**

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key><integer>3</integer>
    <key>Minute</key><integer>0</integer>
</dict>
```

Loaded into launchd via:

```bash
cp com.council.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.council.sync.plist
```

---

### 6. Git + SSH Setup

**On Mac Mini:**

```bash
ssh-keygen -t ed25519 -C "council-mac-mini"
# Add ~/.ssh/id_ed25519.pub to GitHub repo deploy keys (write access)
# Test: ssh -T git@github.com
```

Remote must be SSH format:

```
git remote set-url origin git@github.com:username/council.git
```

---

## Environment Variables (`.env`)

```
# Scrapers (existing, used by scrapers/youtube.py and scrapers/lyn_alden_blog.py)
YOUTUBE_API_KEY=your_youtube_data_api_v3_key
LYN_ALDEN_USERNAME=your_lynalden_username
LYN_ALDEN_PASSWORD=your_lynalden_password

# RAG stack (planned, used by ingest.py, council.py, app.py)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=llama3.1:8b
CHROMA_PATH=./chroma_db

# Web app auth (planned)
COUNCIL_USER=your_username
COUNCIL_PASSWORD=your_password
```

Note: the existing Lyn Alden scraper expects `LYN_ALDEN_USERNAME` (not `_EMAIL`).

---

## Setup Sequence (Mac Mini, first time)

1. Install Ollama: `brew install ollama`
2. Pull models: `ollama pull nomic-embed-text && ollama pull llama3.1:8b`
3. Clone repo, create `venv` (`python -m venv venv && source venv/bin/activate`), install `requirements.txt`
4. Install Playwright browsers (required by the Lyn Alden scraper): `playwright install chromium`
5. Copy `.env.example` to `.env`, fill in credentials
6. (Optional, if not using the committed corpus) Run `python scrape.py` — scrape all sources
7. Run `python ingest.py` — initial ingestion of all ~715 files
8. Run `uvicorn app:app --host 0.0.0.0 --port 8000` — verify UI accessible from another device
9. Configure SSH key and test push to GitHub
10. Install launchd plist and verify sync runs

---

## Requirements

Existing (scraping layer — already in `requirements.txt`):

```
requests
playwright
markdownify
youtube-transcript-api
google-api-python-client
python-dotenv
python-frontmatter
```

To be added (RAG + web layer):

```
chromadb
ollama
fastapi
uvicorn
jinja2
python-multipart
```

Note: the Lyn Alden scraper uses Playwright (not `requests + beautifulsoup4`) because the blog requires an authenticated session with a nonce-based login form. Frontmatter is handled by `python-frontmatter`, not `pyyaml`.

---

## Outstanding Decision

**Ollama chat model** — dependent on Mac Mini RAM once powered up:

| RAM  | Recommended model                       |
| ---- | --------------------------------------- |
| 8GB  | llama3.2:3b (limited quality)           |
| 16GB | llama3.1:8b                             |
| 32GB | llama3.1:8b or mistral:7b comfortably   |
| 64GB | llama3.3:70b (quantised) — best quality |

Update `OLLAMA_CHAT_MODEL` in `.env` accordingly. No code changes required.

---

## Future Extensions (out of scope for now)

- **Tailscale** — access the web UI outside the home network
- **Additional advisors** — new creator = new scraper + new ChromaDB collection, no structural changes needed
- **Streaming responses** — stream the LLM output to the UI token by token rather than waiting for full completion
- **Conversation memory** — persist chat history across sessions
