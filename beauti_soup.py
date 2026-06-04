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

BASE_URL = 'https://blacked.com/videos'
MAX_PAGES = 5   # ← change this to however many pages you want

os.makedirs('downloaded_images', exist_ok=True)
all_image_urls = set()

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
}

# ── Setup Brave ──────────────────────────────────────────────
options = webdriver.ChromeOptions()
options.binary_location = r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'
# options.add_argument('--headless')   # uncomment to run without opening browser
options.add_argument('--incognito')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument(f'user-agent={headers["User-Agent"]}')

driver = webdriver.Chrome(
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

    # scan raw HTML for buried image URLs
    for raw_url in re.findall(r'https?://[^\s\'"<>]+\.(?:jpg|jpeg|png|webp|gif)', html):
        found.add(raw_url.split('?')[0])

    return found

def scroll_to_bottom(driver):
    """Scroll down so lazy-loaded images appear in the DOM."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def click_next_page(driver, page_num):
    """Try to click the next page button. Returns True if clicked."""

    # 1. Named next-button selectors (Amazon, generic)
    selectors = [
        'a.s-pagination-next',
        'a[aria-label="Go to next page"]',
        'li.a-last a',
        'a[rel="next"]',
        'a.next',
        'li.next a',
        '.pagination a[aria-label="Next"]',
    ]
    for selector in selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed() and btn.is_enabled():
                driver.execute_script("arguments[0].click();", btn)
                return True
        except NoSuchElementException:
            continue

    # 2. Numbered pagination — find <a> whose text == page_num + 1
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

# ── Crawl pages ───────────────────────────────────────────────
def wait_for_page_load(driver, timeout=15):
    """Wait until the page JS finishes loading."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    # extra buffer for JS-rendered images to appear in DOM
    time.sleep(3)

try:
    driver.get(BASE_URL)
    wait_for_page_load(driver)
    page_num = 1

    while True:
        print(f"\n[Page {page_num}] {driver.current_url}")

        scroll_to_bottom(driver)   # trigger lazy-load
        wait_for_page_load(driver) # wait again after scroll

        page_images = collect_images(driver.page_source, driver.current_url)
        new = page_images - all_image_urls
        all_image_urls.update(page_images)
        print(f"  Found {len(new)} new images (total: {len(all_image_urls)})")

        prev_url = driver.current_url

        if page_num >= MAX_PAGES:
            print(f"  Reached page limit ({MAX_PAGES}) — stopping.")
            break

        if not click_next_page(driver, page_num):
            print("  No next page found — done crawling.")
            break

        # wait for URL or content to actually change
        try:
            WebDriverWait(driver, 15).until(lambda d: d.current_url != prev_url)
        except Exception:
            pass  # some sites paginate without changing URL (JS state)

        wait_for_page_load(driver)
        page_num += 1

finally:
    driver.quit()

# ── Download all images ───────────────────────────────────────
print(f"\n─── Downloading {len(all_image_urls)} images ───\n")

for i, img_url in enumerate(all_image_urls):
    ext = os.path.splitext(urlparse(img_url).path)[-1] or '.jpg'
    filename = f'downloaded_images/image_{i}{ext}'
    try:
        res = requests.get(img_url, headers=headers, timeout=10)
        if res.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(res.content)
            print(f"Saved: {filename}")
        else:
            print(f"Skipped ({res.status_code}): {img_url}")
    except Exception as e:
        print(f"Failed: {img_url} ({e})")

print("\nDone.")
