import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
}
BRAVE_PATH = r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'


def setup_driver(headless=False):
    options = webdriver.ChromeOptions()
    options.binary_location = BRAVE_PATH
    options.add_argument('--incognito')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument(f'user-agent={HEADERS["User-Agent"]}')
    if headless:
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
    return webdriver.Chrome(
        service=Service(ChromeDriverManager(driver_version="148").install()),
        options=options
    )


def collect_images(html, page_url):
    soup = BeautifulSoup(html, 'lxml')
    found = set()

    def collect(img_url):
        if not img_url:
            return
        img_url = img_url.strip().split('?')[0]
        if img_url.startswith('data:'):
            return
        img_url = urljoin(page_url, img_url)
        if re.search(r'\.(jpg|jpeg|png|webp|gif|svg)$', img_url, re.I):
            found.add(img_url)

    for tag in soup.find_all('img'):
        for attr in ('src', 'data-src', 'data-lazy-src', 'data-original', 'data-lazy'):
            collect(tag.get(attr))
        for part in (tag.get('srcset') or '').split(','):
            collect(part.strip().split(' ')[0])

    for tag in soup.find_all('source'):
        for part in (tag.get('srcset') or '').split(','):
            collect(part.strip().split(' ')[0])

    for tag in soup.find_all(style=True):
        for m in re.findall(r'url\(["\']?(.*?)["\']?\)', tag['style']):
            collect(m)

    for tag in soup.find_all('video'):
        collect(tag.get('poster'))

    for tag in soup.find_all('iframe'):
        m = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]+)', tag.get('src') or '')
        if m:
            found.add(f'https://img.youtube.com/vi/{m.group(1)}/hqdefault.jpg')

    for raw_url in re.findall(r'https?://[^\s\'"<>]+\.(?:jpg|jpeg|png|webp|gif)', html):
        found.add(raw_url.split('?')[0])

    return found


def scroll_to_bottom(driver, stop_event=None):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        if stop_event and stop_event.is_set():
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def wait_for_page_load(driver, timeout=15):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(3)


def click_next_page(driver, page_num):
    named_selectors = [
        'a.s-pagination-next',
        'a[aria-label="Go to next page"]',
        'li.a-last a',
        'a[rel="next"]',
        'a.next',
        'li.next a',
        '.pagination a[aria-label="Next"]',
    ]
    for selector in named_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed() and btn.is_enabled():
                driver.execute_script("arguments[0].click();", btn)
                return True
        except NoSuchElementException:
            continue

    # Numbered pagination: find link whose text == page_num + 1
    next_num = str(page_num + 1)
    for a in driver.find_elements(By.TAG_NAME, 'a'):
        try:
            if a.text.strip() == next_num and a.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView(true);", a)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", a)
                return True
        except Exception:
            continue

    return False


def download_images(image_urls, output_dir, log=None):
    saved = []
    for i, img_url in enumerate(image_urls):
        ext = os.path.splitext(urlparse(img_url).path)[-1] or '.jpg'
        filename = os.path.join(output_dir, f"image_{i}{ext}")
        try:
            res = requests.get(img_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(res.content)
                saved.append(filename)
                if log:
                    log(f"Saved: image_{i}{ext}")
        except Exception as e:
            if log:
                log(f"Failed: {img_url} ({e})")
    return saved


def run_scraper(url, max_pages, output_dir, headless=False, log=None, stop_event=None):
    """
    Main entry point. Crawls `url` for `max_pages` pages,
    collects all image URLs, downloads them to `output_dir`.
    `log(msg)` is called for live progress updates.
    `stop_event` is a threading.Event — set it to stop early.
    Returns list of saved file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    all_image_urls = set()

    def emit(msg):
        if log:
            log(msg)

    def is_stopped():
        return stop_event is not None and stop_event.is_set()

    driver = setup_driver(headless=headless)
    try:
        driver.get(url)
        wait_for_page_load(driver)

        for page_num in range(1, max_pages + 1):
            if is_stopped():
                emit("Stopped by user.")
                break

            emit(f"Scraping page {page_num} — {driver.current_url}")
            scroll_to_bottom(driver, stop_event=stop_event)
            wait_for_page_load(driver)

            if is_stopped():
                emit("Stopped by user.")
                break

            page_images = collect_images(driver.page_source, driver.current_url)
            new = page_images - all_image_urls
            all_image_urls.update(page_images)
            emit(f"  Found {len(new)} new images (total: {len(all_image_urls)})")

            if page_num >= max_pages:
                emit(f"Reached page limit ({max_pages}). Stopping.")
                break

            prev_url = driver.current_url
            if not click_next_page(driver, page_num):
                emit("No more pages found.")
                break

            try:
                WebDriverWait(driver, 15).until(lambda d: d.current_url != prev_url)
            except Exception:
                pass
            wait_for_page_load(driver)

    finally:
        driver.quit()

    if all_image_urls:
        emit(f"Downloading {len(all_image_urls)} images to '{output_dir}/'...")
        saved = download_images(all_image_urls, output_dir, log=emit)
        emit(f"Done. {len(saved)} images saved.")
        return saved

    return []
