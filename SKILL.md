---
name: buondua-downloader
description: Parses an album page on buondua.com and downloads all high-resolution photos across all pages, resolving lazy-loaded images.
license: GPL-3.0
metadata:
  version: "1.0"
  author: Antigravity
---

# Buondua Downloader Skill

This skill enables the OpenClaw agent to extract and download photo albums from `buondua.com`. It is designed to navigate multi-page galleries, trigger lazy-loaded images, filter out layout components, and download photos without being blocked by anti-bot protections.

## How to Invoke

To download an album, call the Python script:
```bash
python scripts/download_album.py "<album-url>" --output-dir "<destination-folder>"
```

### Script Arguments

- `url` (Positional, Required): The exact URL of the buondua.com album (e.g. `https://buondua.com/album/some-album-title`).
- `-o`, `--output-dir` (Optional): The parent directory to save photos. Defaults to `./downloads`. A clean subfolder named after the album's title will be created inside this folder.
- `--headless` (Optional, flag): Run Playwright in headless mode (default: True). Use `--no-headless` to run with browser visible.
- `--scroll-delay` (Optional): Time in seconds to wait after each incremental scroll to allow lazy loading (default: 0.5).
- `--download-delay` (Optional): Delay in seconds between image downloads to prevent server overload and rate limiting (default: 0.3).
- `--timeout` (Optional): Page load/navigation timeout in milliseconds (default: 30000).

## Core Scraper Workflow

1. **Launches Playwright:** Initializes a Chromium browser instance using a desktop User-Agent to match standard browser requests.
2. **Page Navigation & Metadata Detection:**
   - Navigates to the initial album URL.
   - Extracts the clean album title from the `<h1>` heading to construct the target download folder.
3. **Pagination Mapping:**
   - Evaluates all links (`<a>` elements) on the initial page.
   - Identifies page URLs belonging to the same album (e.g., URLs matching `?page=X` or `/page/X` query/path structures).
   - Maps and sorts the entire set of pages sequentially.
4. **Lazy Loading Trigger:**
   - For each page, scrolls down in incremental steps (by 80% viewport height), pausing to trigger and let the lazy-loaded image loads complete.
5. **Robust Photo Filtering:**
   - Extracts the image sources from `<img>` elements.
   - Automatically filters out small UI components, sidebar items, recommended album thumbnails, ads, and icons by assessing natural physical image dimensions (naturalWidth >= 300px and naturalHeight >= 300px).
   - Checks both `src` and data attributes (like `data-src`, `data-original`, etc.) to find the highest-resolution URL.
6. **Network-Context Downloads:**
   - Performs downloads using Playwright's network-request layer (`page.request.get`). This automatically inherits all valid session headers, cookies, and user-agent settings from the rendered session, bypassing 403 Forbidden checks.
   - Saves files sequentially (e.g., `001.jpg`, `002.jpg`, etc.) in the destination subfolder.
