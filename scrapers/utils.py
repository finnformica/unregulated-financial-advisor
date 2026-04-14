import json
from datetime import datetime


def load_last_synced(scraper_name: str) -> str | None:
    try:
        with open("last_synced.json", "r") as f:
            data = json.load(f)
            timestamp = data.get(scraper_name, None)
            return datetime.fromisoformat(timestamp) if timestamp else None
    except FileNotFoundError:
        return None


def save_last_synced(scraper_name: str) -> None:
    try:
        with open("last_synced.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    data[scraper_name] = datetime.now().isoformat()

    with open("last_synced.json", "w") as f:
        json.dump(data, f, indent=4)
