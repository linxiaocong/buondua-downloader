#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import asyncio
from urllib.parse import urlparse, urljoin, parse_qs, unquote
from playwright.async_api import async_playwright

# Reconfigure stdout/stderr to UTF-8 on Windows or other non-UTF-8 terminals
# to avoid UnicodeEncodeErrors with international characters in album titles
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Standard User-Agent to mimic a real desktop browser
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def clean_filename(name):
    """
    Remove invalid characters for file and folder names in Windows/Unix.
    """
    # Replace invalid chars with space or remove them
    cleaned = re.sub(r'[\\/*?:"<>|]', ' ', name)
    # Collapse multiple spaces and strip
    return re.sub(r'\s+', ' ', cleaned).strip()


def extract_page_number(url):
    """
    Extract the page number from the URL to sort pages correctly.
    """
    # Try query parameters: ?page=X or &page=X or ?p=X
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    for p_arg in ['page', 'p']:
        if p_arg in query_params:
            try:
                return int(query_params[p_arg][0])
            except ValueError:
                pass

    # Try path segment: /page/X or /page-X or /p/X
    path_match = re.search(r'/(?:page|p|page-)(\d+)(?:/|$)', parsed.path)
    if path_match:
        return int(path_match.group(1))

    # Try general trailing page digits: /album-name/X
    last_segment = parsed.path.strip('/').split('/')[-1]
    if last_segment.isdigit():
        return int(last_segment)

    return 1


async def scroll_page_to_trigger_lazy_load(page, scroll_delay):
    """
    Scroll the page down incrementally to trigger lazy loaded images.
    """
    print("[+] Triggering lazy loading by scrolling...")
    viewport_height = await page.evaluate("window.innerHeight")
    total_height = await page.evaluate("document.body.scrollHeight")
    current_position = 0

    while current_position < total_height:
        # Scroll to current offset
        await page.evaluate(f"window.scrollTo(0, {current_position})")
        await asyncio.sleep(scroll_delay)
        
        # Advance by 80% of viewport to ensure overlap and capture all triggers
        current_position += int(viewport_height * 0.8)
        total_height = await page.evaluate("document.body.scrollHeight")

    # Scroll to absolute bottom
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(scroll_delay)
    
    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.5)


async def get_page_images(page, base_url):
    """
    Extract all image elements on the page, filters out UI components,
    and returns absolute high-resolution URLs.
    """
    # Run Javascript evaluation to batch extract DOM properties (highly efficient)
    raw_images = await page.evaluate("""
        () => {
            const container = document.querySelector('.article-fulltext') || document;
            const imgs = container.querySelectorAll('img');
            const data = [];
            for (const img of imgs) {
                // Get raw attributes
                const src = img.src;
                const dataSrc = img.getAttribute('data-src') || 
                                img.getAttribute('data-original') || 
                                img.getAttribute('data-lazy-src') || 
                                img.getAttribute('data-srcset');
                
                // Get width and height (natural if available, otherwise CSS/attributes)
                const width = img.naturalWidth || img.width || 0;
                const height = img.naturalHeight || img.height || 0;
                const complete = img.complete;
                
                data.push({
                    src: src,
                    dataSrc: dataSrc,
                    width: width,
                    height: height,
                    complete: complete
                });
            }
            return data;
        }
    """)

    image_urls = []
    for img in raw_images:
        src = img['src']
        data_src = img['dataSrc']
        width = img['width']
        height = img['height']

        # Determine the high-resolution URL (prefer data-src over src)
        candidate_url = data_src if data_src else src
        if not candidate_url:
            continue

        # Resolve relative URLs
        absolute_url = urljoin(base_url, candidate_url).strip()

        # Skip data URLs
        if absolute_url.lower().startswith('data:'):
            continue

        # Physical dimension-based filtering to remove layout icons, avatars, and sidebars
        # Main photosets have large high-resolution images
        if width > 0 and height > 0:
            if width < 300 or height < 300:
                # Small thumbnail or icon, skip
                continue
        else:
            # If dimensions are 0 (e.g. not loaded or hidden), fall back to checking URL path patterns.
            # Usually logos or icons have 'logo', 'avatar', 'icon', 'theme' in their path.
            lower_url = absolute_url.lower()
            if any(term in lower_url for term in ['logo', 'avatar', 'icon', 'banner', 'theme', 'nav', 'loader']):
                continue

        if absolute_url not in image_urls:
            image_urls.append(absolute_url)

    return image_urls


async def extract_pagination_urls(page, start_url):
    """
    Extract all unique page URLs belonging to the current album.
    """
    print("[+] Extracting pagination links...")
    parsed_start = urlparse(start_url)
    # Decode percent-encoding so we can compare against decoded hrefs from the page DOM
    start_path = unquote(parsed_start.path.rstrip('/'))

    # Get all links on the page
    links = await page.query_selector_all("a")
    page_urls = {start_url}

    for link in links:
        href = await link.get_attribute("href")
        if not href:
            continue
        
        # Resolve relative URLs
        absolute_url = urljoin(start_url, href).strip()
        parsed_abs = urlparse(absolute_url)

        # Must belong to the same domain/host
        if parsed_abs.netloc != parsed_start.netloc:
            continue

        # Decode both sides before comparing to handle percent-encoded Unicode in URLs
        abs_path = unquote(parsed_abs.path.rstrip('/'))
        
        # Check if the base path is identical (e.g., /album-slug)
        if abs_path == start_path:
            # Look for page parameters
            query_params = parse_qs(parsed_abs.query)
            if 'page' in query_params or 'p' in query_params:
                page_urls.add(absolute_url)
        # Check if it is a subpath representing page numbers (e.g., /album-slug/2 or /album-slug/page/2)
        elif abs_path.startswith(start_path):
            remaining = abs_path[len(start_path):].strip('/')
            if remaining.isdigit() or remaining.startswith('page/') or re.search(r'page/\d+', remaining):
                page_urls.add(absolute_url)

    # Sort the page URLs numerically
    sorted_page_urls = sorted(list(page_urls), key=extract_page_number)
    return sorted_page_urls


async def download_image(page, img_url, dest_path, referer, retries=2):
    """
    Download image using Playwright's native network client to inherit cookies and User-Agent.
    """
    for attempt in range(retries + 1):
        try:
            # Playwright API context request get
            response = await page.request.get(img_url, headers={
                "Referer": referer,
                "User-Agent": DEFAULT_USER_AGENT
            })
            if response.status == 200:
                data = await response.body()
                with open(dest_path, "wb") as f:
                    f.write(data)
                return True
            else:
                print(f"[-] Attempt {attempt+1}: Received status {response.status} for {img_url}")
        except Exception as e:
            print(f"[-] Attempt {attempt+1}: Exception downloading {img_url} - {e}")
        
        if attempt < retries:
            await asyncio.sleep(1.0)
            
    return False


async def run_downloader(args):
    url = args.url
    output_parent = args.output_dir
    headless = args.headless
    scroll_delay = args.scroll_delay
    download_delay = args.download_delay
    timeout = args.timeout

    print(f"[+] Starting OpenClaw Buondua Scraper")
    print(f"[+] Album URL: {url}")
    print(f"[+] Output Directory: {output_parent}")

    async with async_playwright() as p:
        print("[+] Launching browser...")
        browser = await p.chromium.launch(headless=headless)
        
        # Configure context with desktop viewport and User-Agent
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1920, "height": 1080}
        )
        
        # Create a new page and set default navigation timeout
        page = await context.new_page()
        page.set_default_timeout(timeout)

        print(f"[+] Navigating to: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[-] Initial page load timeout/error: {e}. Attempting to proceed anyway.")

        # Extract Album Title for target directory
        album_title = "Buondua Album"
        try:
            # Look for main page title header
            h1_el = await page.query_selector("h1")
            if h1_el:
                title_text = await h1_el.inner_text()
                if title_text:
                    album_title = title_text.strip()
        except Exception as e:
            print(f"[-] Could not parse album title, using default: {e}")

        clean_album_title = clean_filename(album_title)
        album_dir = os.path.join(output_parent, clean_album_title)
        os.makedirs(album_dir, exist_ok=True)
        print(f"[+] Target download directory: {album_dir}")

        # Resolve the canonical URL from the page — the server may normalize special characters
        # in the URL (e.g. '…' → 'yeha-hina'), so we must use the server's actual slug for
        # pagination link matching, not the user-supplied URL which may differ.
        canonical_url = url
        try:
            canonical_el = await page.query_selector("link[rel='canonical']")
            if canonical_el:
                canonical_href = await canonical_el.get_attribute("href")
                if canonical_href:
                    # Strip any ?page=N suffix from the canonical URL to get base URL
                    canonical_base = canonical_href.split("?")[0].rstrip("/")
                    if canonical_base:
                        canonical_url = canonical_base
                        if canonical_url != url:
                            print(f"[+] Canonical URL resolved: {canonical_url}")
        except Exception as e:
            print(f"[-] Could not resolve canonical URL, using original: {e}")

        # Map all album page URLs using the canonical URL as the base
        page_urls = await extract_pagination_urls(page, canonical_url)
        print(f"[+] Found {len(page_urls)} album pages to download:")
        for idx, p_url in enumerate(page_urls, 1):
            print(f"    Page {idx}: {p_url}")

        img_counter = 0
        all_unique_images = set()

        # Create a queue for download tasks
        queue = asyncio.Queue()

        # Track successfully downloaded count
        stats = {
            "downloaded": 0,
            "failed": 0
        }

        # Background worker for downloading images sequentially
        async def download_worker():
            while True:
                task = await queue.get()
                if task is None:
                    queue.task_done()
                    break
                
                img_idx, img_url = task
                parsed_path = urlparse(img_url).path
                _, ext = os.path.splitext(parsed_path)
                if not ext or len(ext) > 5:  # Handle cases without clear extensions
                    ext = ".jpg"
                
                # Format filename as 001.jpg, 002.jpg, etc.
                filename = f"{img_idx:03d}{ext}"
                dest_path = os.path.join(album_dir, filename)

                print(f"[+] [{img_idx}] Downloading {filename}...")
                
                success = await download_image(page, img_url, dest_path, referer=url)
                if success:
                    stats["downloaded"] += 1
                    # Wait briefly between downloads to avoid rate limits
                    await asyncio.sleep(download_delay)
                else:
                    print(f"[-] Failed to download image {img_idx}: {img_url}")
                    stats["failed"] += 1
                
                queue.task_done()

        # Start the background download worker task
        worker_task = asyncio.create_task(download_worker())

        # Process page by page
        for page_idx, target_page_url in enumerate(page_urls, 1):
            print(f"\n[+] Processing Page {page_idx}/{len(page_urls)}: {target_page_url}")
            
            # Navigate if not already on the first page
            if page_idx > 1:
                try:
                    await page.goto(target_page_url, wait_until="domcontentloaded")
                except Exception as e:
                    print(f"[-] Page {page_idx} load failed: {e}. Skipping page.")
                    continue

            # Scroll step-by-step to load lazy images
            await scroll_page_to_trigger_lazy_load(page, scroll_delay)

            # Extract high-res image URLs
            page_images = await get_page_images(page, target_page_url)
            print(f"[+] Found {len(page_images)} matching images on Page {page_idx}")

            # Keep track of unique image URLs overall to avoid duplicates
            for img_url in page_images:
                if img_url not in all_unique_images:
                    all_unique_images.add(img_url)
                    img_counter += 1
                    await queue.put((img_counter, img_url))

        # Wait for all queued items to finish downloading
        print("\n[+] Finished parsing all pages. Waiting for remaining downloads to complete...")
        await queue.join()

        # Stop worker
        await queue.put(None)
        await worker_task

        print(f"\n[+] Download completed successfully!")
        print(f"[+] Total photos downloaded: {stats['downloaded']}/{img_counter}")
        print(f"[+] Folder location: {os.path.abspath(album_dir)}")

        await browser.close()


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Buondua Album Downloader")
    parser.add_argument("url", help="The URL of the buondua.com album to download")
    parser.add_argument("-o", "--output-dir", default="./downloads", help="The parent directory to save photos")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run with visible browser window")
    parser.add_argument("--scroll-delay", type=float, default=0.5, help="Delay in seconds between scroll steps")
    parser.add_argument("--download-delay", type=float, default=0.3, help="Delay in seconds between image downloads")
    parser.add_argument("--timeout", type=int, default=30000, help="Navigation and page load timeout in milliseconds")
    
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    asyncio.run(run_downloader(args))


if __name__ == "__main__":
    main()
