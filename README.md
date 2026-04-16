# Council of Advisors

A fully local, private financial research assistant. Scrapes content from two financial creators (Ben Cowen via YouTube, Lyn Alden via her paid blog) on a schedule, indexes each creator's corpus into its own vector store, and answers questions by generating a grounded response from each creator in their own voice followed by a synthesised council summary. Runs on a Mac Mini on the home network, accessible from any device via a private web UI. No external API costs.

See [`MASTER_PLAN.md`](./MASTER_PLAN.md) for the full architectural specification.

## Setup

First-time setup on the Mac Mini:

1. Install Ollama: `brew install ollama`
2. Pull models: `ollama pull nomic-embed-text && ollama pull llama3.1:8b`
3. Create a virtualenv and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Install Playwright browsers (required by the Lyn Alden scraper):
   ```bash
   playwright install chromium
   ```
5. Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```
6. (Optional, if not using the committed corpus) Scrape all sources: `python scrape.py`
7. Initial ingestion into ChromaDB: `python ingest.py`
8. Start the server (see below) and verify it's reachable from another device on the network.
9. Configure an SSH deploy key for the GitHub remote so `sync.sh` can push.
10. Install the launchd plist to run `sync.sh` on a schedule:
    ```bash
    cp com.council.sync.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.council.sync.plist
    ```

## Running the server

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Binds to `0.0.0.0` so the UI is reachable from any device on the home network at `http://<mac-mini-ip>:8000`. Access is protected by HTTP Basic Auth using `COUNCIL_USER` / `COUNCIL_PASSWORD` from `.env`.

## Manually triggering a sync

Two options, depending on scope:

- **Scrape only** (fetch new content, no ingestion or push):
  ```bash
  python scrape.py
  ```
- **Full pipeline** (scrape → ingest → commit → push):
  ```bash
  bash sync.sh
  ```

`sync.sh` is the same script launchd runs on its schedule.

## Project layout

```
scrapers/       scrapers for each creator (YouTube, Lyn Alden blog)
files/          scraped markdown corpus, one subdir per scraper
scrape.py       entrypoint that runs all scrapers
ingest.py       chunks + embeds + upserts markdown into ChromaDB
council.py      RAG + advisor + synthesis logic
app.py          FastAPI web server
templates/      Jinja2 templates for the chat UI
static/         CSS for the chat UI
sync.sh         weekly scrape → ingest → git push pipeline
```

Refer to [`MASTER_PLAN.md`](./MASTER_PLAN.md) for component specs, the frontmatter schema, and configuration details.
