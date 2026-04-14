from scrapers.youtube import YouTubeScraper
from scrapers.lyn_alden_blog import LynAldenBlogScraper

if __name__ == "__main__":
    LynAldenBlogScraper().run()
    YouTubeScraper(
        handle="@intothecryptoverse",
        creator="Ben Cowen",
        full_sync_from="2022-06-01",
    ).run()
