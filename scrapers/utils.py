import json
import frontmatter
from pathlib import Path
from datetime import datetime, date


def get_file_path(scraper_name: str, title: str) -> Path:
    safe_title = "".join(
        c for c in title if c.isalnum() or c in (" ", "_", "-")
    ).rstrip()
    filepath = Path("files") / scraper_name / f"{safe_title}.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    return filepath


def write_markdown(
    filepath: Path,
    content: str,
    title: str,
    url: str,
    creator: str,
    source: str,
    date: date,
) -> None:
    post = frontmatter.Post(
        content=content,
        title=title,
        url=url,
        creator=creator,
        source=source,
        date=str(date),
    )

    with open(filepath, "w") as f:
        f.write(frontmatter.dumps(post))


def load_last_synced(scraper_name: str) -> datetime | None:
    try:
        with open("last_synced.json", "r") as f:
            data = json.load(f)
            timestamp = data.get(scraper_name, None)
            return (
                datetime.fromisoformat(timestamp).replace(tzinfo=None)
                if timestamp
                else None
            )
    except FileNotFoundError:
        return None


def save_last_synced(scraper_name: str, date: datetime | None = None) -> None:
    try:
        with open("last_synced.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    data[scraper_name] = (date or datetime.now()).isoformat()

    with open("last_synced.json", "w") as f:
        json.dump(data, f, indent=4)
