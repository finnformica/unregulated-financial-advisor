# scrapers/youtube.py

import os
import time
import random
from datetime import datetime
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build

from utils import get_file_path, load_last_synced, save_last_synced, write_markdown

load_dotenv()

yt_transcribe_client = YouTubeTranscriptApi()


class YouTubeScraper:
    def __init__(self, handle: str, creator: str):
        self.creator = creator
        self.scraper_name = f"{creator.lower().replace(' ', '_')}_youtube"
        self.youtube = build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))
        self.channel_id = self._get_channel_id(handle.lstrip("@"))

    def _get_channel_id(self, handle: str) -> str:
        response = self.youtube.channels().list(part="id", forHandle=handle).execute()
        if not response.get("items"):
            raise ValueError(f"Could not find channel for handle: {handle}")
        return response["items"][0]["id"]

    def get_uploads_playlist_id(self) -> str:
        response = (
            self.youtube.channels()
            .list(part="contentDetails", id=self.channel_id)
            .execute()
        )
        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def get_video_ids(
        self, playlist_id: str, last_synced: datetime | None
    ) -> list[dict]:
        videos = []
        next_page_token = None

        while True:
            response = (
                self.youtube.playlistItems()
                .list(
                    part="snippet",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page_token,
                )
                .execute()
            )

            for item in response["items"]:
                snippet = item["snippet"]
                published_at = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                )

                if last_synced and published_at <= last_synced:
                    return videos

                videos.append(
                    {
                        "id": snippet["resourceId"]["videoId"],
                        "title": snippet["title"],
                        "date": published_at,
                    }
                )

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        return videos

    def get_transcript(self, video_id: str) -> str | None:
        try:
            transcript = yt_transcribe_client.fetch(video_id).to_raw_data()
            chunks = []
            for entry in transcript:
                minutes = int(entry["start"]) // 60
                seconds = int(entry["start"]) % 60
                chunks.append(f"[{minutes:02d}:{seconds:02d}] {entry['text']}")
            return "\n".join(chunks)
        except Exception as e:
            print(f"Could not fetch transcript for {video_id}: {e}")
            return None

    def run(self) -> None:
        last_synced = load_last_synced(self.scraper_name)
        playlist_id = self.get_uploads_playlist_id()
        videos = self.get_video_ids(playlist_id, last_synced)

        print(f"Found {len(videos)} new videos for {self.creator}")

        successful_dates = []
        for video in videos:
            print(f"Scraping: {video['title']}")

            transcript = self.get_transcript(video["id"])
            if not transcript:
                continue

            filepath = get_file_path(self.scraper_name, video["title"])
            write_markdown(
                filepath=filepath,
                content=transcript,
                title=video["title"],
                url=f"https://www.youtube.com/watch?v={video['id']}",
                creator=self.creator,
                source="youtube",
                date=video["date"],
            )

            successful_dates.append(video["date"])
            time.sleep(random.uniform(1, 3))

        if successful_dates:
            save_last_synced(self.scraper_name, max(successful_dates))


if __name__ == "__main__":
    YouTubeScraper(handle="@intothecryptoverse", creator="Ben Cowen").run()
