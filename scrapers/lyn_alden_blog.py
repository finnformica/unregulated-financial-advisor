import os
import time
import random
import frontmatter
from datetime import datetime
from dotenv import load_dotenv
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright, Page

from utils import get_file_path, load_last_synced, save_last_synced

load_dotenv()

SCRAPER_NAME = "lyn_alden_blog"

BASE_URL = "https://www.lynalden.com"
LOGIN_URL = f"{BASE_URL}/login/"
MEMBERS_URL = f"{BASE_URL}/members/"

username = os.getenv("LYN_ALDEN_USERNAME")
password = os.getenv("LYN_ALDEN_PASSWORD")
if not username or not password:
    raise ValueError("Missing LYN_ALDEN_USERNAME or LYN_ALDEN_PASSWORD in .env")


def get_nonce(page: Page) -> str:
    nonce = page.get_attribute("input[name='rcp_login_nonce']", "value")
    if not nonce:
        raise ValueError("Nonce not found")
    print(f"Nonce: {nonce}")


def login(page: Page) -> None:
    page.goto(LOGIN_URL)
    print(f"Landed on: {page.url}")

    get_nonce(page)  # Verify the page loaded correctly

    page.locator("input[name='rcp_user_login']").fill(username)
    page.locator("input[name='rcp_user_pass']").fill(password)
    page.locator("input[type='submit']", has_text="Login").click()

    page.wait_for_load_state("networkidle")

    if MEMBERS_URL not in page.url:
        raise ValueError(f"Login failed, landed on {page.url}")

    print("Login successful")


def get_blog_links(page: Page) -> list[dict[str, str]]:
    last_synced = load_last_synced(SCRAPER_NAME)

    # Find blog post links (contained as <li> inside <ul>)
    links = page.locator("ul li a[href*='/premium-']").all()
    blog_links = []

    for link in links:
        title = link.text_content()
        if len(title.split(":")) < 2:
            continue

        date_str = title.split(":")[0].strip()
        date = datetime.strptime(date_str, "%B %d, %Y")
        if last_synced and date <= last_synced:
            continue

        href = link.get_attribute("href")
        blog_links.append({"title": title, "href": href, "date": date})

    print(f"Found {len(blog_links)} links")

    return blog_links


def extract_and_save_blog_posts(page, blog_links: list[dict[str, str]]) -> None:
    success = True
    for blog in blog_links:
        print(f"Extracting {blog['title']} from {blog['href']}")

        try:
            page.goto(blog["href"])
            page.wait_for_load_state("networkidle")

            article_html = page.locator("article").inner_html()
            markdown = md(article_html, heading_style="ATX")

            post = frontmatter.Post(
                content=markdown,
                title=blog["title"],
                url=blog["href"],
                creator="Lyn Alden",
                source="blog",
                date=blog["date"].isoformat(),
            )

            filepath = get_file_path(SCRAPER_NAME, blog["title"])
            with open(filepath, "w") as f:
                f.write(frontmatter.dumps(post))

        except Exception as e:
            print(f"Error extracting {blog['title']}: {e}")
            success = False

        # Sleep a random amount of time
        r = random.random()
        time.sleep(1 + r * 2)

    return success


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        login(page)

        blog_links = get_blog_links(page)
        success = extract_and_save_blog_posts(page, blog_links)

        # Only update last synced if all posts were successfully extracted
        if success:
            save_last_synced(SCRAPER_NAME)
        browser.close()


if __name__ == "__main__":
    run()
