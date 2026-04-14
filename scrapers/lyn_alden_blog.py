import os
from playwright.sync_api import sync_playwright, Page, BrowserContext
from dotenv import load_dotenv
from utils import load_last_synced, save_last_synced

load_dotenv()

SCRAPER_NAME = "lyn_alden_blog"

BASE_URL = "https://www.lynalden.com"
LOGIN_URL = f"{BASE_URL}/login/"
MEMBERS_URL = f"{BASE_URL}/members/"


def get_nonce(page: Page) -> str:
    nonce = page.get_attribute("input[name='rcp_login_nonce']", "value")
    if not nonce:
        raise ValueError("Nonce not found")
    print(f"Nonce: {nonce}")
    return nonce


def login(page: Page) -> None:
    page.goto(LOGIN_URL)
    print(f"Landed on: {page.url}")

    get_nonce(page)

    page.locator("input[name='rcp_user_login']").fill(os.getenv("LYN_ALDEN_USERNAME"))
    page.locator("input[name='rcp_user_pass']").fill(os.getenv("LYN_ALDEN_PASSWORD"))
    page.locator("input[type='submit']", has_text="Login").click()

    page.wait_for_load_state("networkidle")
    print(f"After login: {page.url}")

    if MEMBERS_URL not in page.url:
        raise ValueError(f"Login failed, landed on {page.url}")

    print("Login successful")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        login(page)

        last_synced = load_last_synced(SCRAPER_NAME)

        print(f"Last synced: {last_synced}")

        # Ready to scrape
        print(f"Currently on: {page.url}")

        save_last_synced(SCRAPER_NAME)

        browser.close()


if __name__ == "__main__":
    run()
