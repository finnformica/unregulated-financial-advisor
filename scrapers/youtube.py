import os
import re
import time
import random
from datetime import datetime
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build

from .utils import get_file_path, load_last_synced, save_last_synced, write_markdown

load_dotenv()

yt_transcribe_client = YouTubeTranscriptApi()


class YouTubeScraper:
    def __init__(
        self,
        handle: str,
        creator: str,
        full_sync_from: str | None = None,
        min_duration_seconds: int = 60,
        exclude_livestreams: bool = True,
    ):
        self.creator = creator
        self.scraper_name = f"{creator.lower().replace(' ', '_')}_youtube"
        self.full_sync_from = (
            datetime.fromisoformat(full_sync_from).replace(tzinfo=None)
            if full_sync_from
            else None
        )
        self.exclude_filters = {
            "min_duration_seconds": min_duration_seconds,
            "exclude_livestreams": exclude_livestreams,
        }
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

        # On first sync, use full_sync_from as the cutoff if provided
        cutoff = last_synced or self.full_sync_from

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
                ).replace(tzinfo=None)

                if cutoff and published_at <= cutoff:
                    # Return videos in chronological order (oldest first)
                    return list(reversed(videos))

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

        # Return videos in chronological order (oldest first)
        return list(reversed(videos))

    def parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration format to seconds."""
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
        if not match:
            return 0
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    def get_video_details(self, video_ids: list[str]) -> dict:
        """Fetch video details including duration and livestream status."""
        details = {}
        # Process in batches of 50 (API limit)
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            response = (
                self.youtube.videos()
                .list(
                    part="contentDetails,snippet,liveStreamingDetails",
                    id=",".join(batch),
                )
                .execute()
            )

            for item in response["items"]:
                video_id = item["id"]
                details[video_id] = {
                    "duration_seconds": self.parse_duration(
                        item["contentDetails"]["duration"]
                    ),
                    "is_livestream": "liveStreamingDetails" in item
                    or item["snippet"].get("liveBroadcastContent", "none") != "none",
                }
        return details

    def should_skip_video(self, video_details: dict) -> bool:
        """Determine if a video should be skipped based on filters."""
        if not self.exclude_filters:
            return False

        # Check if it's a short (typically < 60 seconds)
        min_duration = self.exclude_filters.get("min_duration_seconds")
        if min_duration and video_details["duration_seconds"] <= min_duration:
            return True

        # Check if it's a livestream
        if (
            self.exclude_filters.get("exclude_livestreams")
            and video_details["is_livestream"]
        ):
            return True

        return False

    def get_transcript(self, video_id: str) -> tuple[str | None, bool]:
        try:
            transcript = yt_transcribe_client.fetch(video_id).to_raw_data()
            chunks = []
            for entry in transcript:
                minutes = int(entry["start"]) // 60
                seconds = int(entry["start"]) % 60
                chunks.append(f"[{minutes:02d}:{seconds:02d}] {entry['text']}")
            return "\n".join(chunks), False
        except Exception as e:
            error_msg = str(e).lower()
            # Check for rate limiting indicators
            if any(
                indicator in error_msg
                for indicator in [
                    "too many requests",
                    "rate limit",
                    "429",
                    "quota",
                    "blocked",
                    "blocking requests",
                    "forbidden",
                    "bot detected",
                    "ip has been blocked",
                    "ip belonging to a cloud provider",
                ]
            ):
                print(f"\n⚠️  Rate limited or IP blocked by YouTube")
                return None, True
            print(f"Could not fetch transcript for {video_id}: {e}")
            return None, False

    def run(self) -> None:
        last_synced = load_last_synced(self.scraper_name)
        playlist_id = self.get_uploads_playlist_id()
        videos = self.get_video_ids(playlist_id, last_synced)

        if not videos:
            print(f"No new videos found for {self.creator}")
            return

        # Get video details for filtering
        video_ids = [v["id"] for v in videos]
        video_details = self.get_video_details(video_ids)

        # Filter videos
        filtered_videos = []
        for video in videos:
            if video["id"] not in video_details:
                continue
            if self.should_skip_video(video_details[video["id"]]):
                continue
            filtered_videos.append(video)

        print(f"Found {len(filtered_videos)} new videos for {self.creator}")

        for idx, video in enumerate(filtered_videos):
            print(
                f"Scraping #{len(filtered_videos) - idx} ({video['date'].strftime('%Y-%m-%d')}): {video['title']}"
            )

            transcript, is_rate_limited = self.get_transcript(video["id"])

            if is_rate_limited:
                print(
                    f"   Failed on: {video['title']} ({video['date'].strftime('%Y-%m-%d')})"
                )
                print(f"   Resume later to continue from this point.")
                break

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

            # Update last_synced after each successful video
            save_last_synced(self.scraper_name, video["date"])
            # Sleep 8-13 seconds between videos to avoid rate limiting
            time.sleep(random.uniform(8, 13))


if __name__ == "__main__":
    YouTubeScraper(
        handle="@intothecryptoverse",
        creator="Ben Cowen",
        full_sync_from="2022-06-01",
    ).run()
