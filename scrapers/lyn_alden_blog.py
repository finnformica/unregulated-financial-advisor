import os
import time
import random
from datetime import datetime
from dotenv import load_dotenv
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright, Page

from .utils import get_file_path, load_last_synced, save_last_synced, write_markdown

load_dotenv()


class LynAldenBlogScraper:
    SCRAPER_NAME = "lyn_alden_blog"
    BASE_URL = "https://www.lynalden.com"
    LOGIN_URL = f"{BASE_URL}/login/"
    MEMBERS_URL = f"{BASE_URL}/members/"

    def __init__(self):
        self.username = os.getenv("LYN_ALDEN_USERNAME")
        self.password = os.getenv("LYN_ALDEN_PASSWORD")
        if not self.username or not self.password:
            raise ValueError("Missing LYN_ALDEN_USERNAME or LYN_ALDEN_PASSWORD in .env")

    def get_nonce(self, page: Page) -> None:
        nonce = page.get_attribute("input[name='rcp_login_nonce']", "value")
        if not nonce:
            raise ValueError("Nonce not found")
        print(f"Nonce: {nonce}")

    def login(self, page: Page) -> None:
        page.goto(self.LOGIN_URL)
        print(f"Landed on: {page.url}")

        self.get_nonce(page)

        page.locator("input[name='rcp_user_login']").fill(self.username)
        page.locator("input[name='rcp_user_pass']").fill(self.password)
        page.locator("input[type='submit']", has_text="Login").click()

        page.wait_for_load_state("networkidle")

        if self.MEMBERS_URL not in page.url:
            raise ValueError(f"Login failed, landed on {page.url}")

        print("Login successful")

    def get_blog_links(self, page: Page) -> list[dict[str, str]]:
        last_synced = load_last_synced(self.SCRAPER_NAME)

        links = page.locator("ul li a[href*='/premium-']").all()
        blog_links = []

        for link in links:
            title = link.text_content()
            if len(title.split(":")) < 2:
                continue

            try:
                date_str = title.split(":")[0].strip()
                date = datetime.strptime(date_str, "%B %d, %Y")
            except ValueError:
                print(f"Could not parse date from title: {title}")
                continue

            if last_synced and date <= last_synced:
                continue

            href = link.get_attribute("href")
            blog_links.append({"title": title, "href": href, "date": date})

        print(f"Found {len(blog_links)} links")
        return blog_links

    def extract_and_save_blog_posts(
        self, page: Page, blog_links: list[dict[str, str]]
    ) -> list[datetime]:
        successful_dates = []
        for blog in blog_links:
            print(f"Extracting {blog['title']} from {blog['href']}")

            try:
                page.goto(blog["href"])
                page.wait_for_load_state("networkidle")

                article_html = page.locator("article").inner_html()
                markdown = md(article_html, heading_style="ATX")
                filepath = get_file_path(self.SCRAPER_NAME, blog["title"])

                write_markdown(
                    filepath=filepath,
                    content=markdown,
                    title=blog["title"],
                    url=blog["href"],
                    creator="Lyn Alden",
                    source="blog",
                    date=blog["date"].isoformat(),
                )

                successful_dates.append(blog["date"])

            except Exception as e:
                print(f"Error extracting {blog['title']}: {e}")

            time.sleep(1 + random.random() * 2)

        return successful_dates

    def run(self) -> None:
        print("Fetching Lyn Alden blog posts")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self.login(page)

            blog_links = self.get_blog_links(page)
            successful_dates = self.extract_and_save_blog_posts(page, blog_links)

            if successful_dates:
                save_last_synced(self.SCRAPER_NAME, max(successful_dates))

            browser.close()


if __name__ == "__main__":
    LynAldenBlogScraper().run()
