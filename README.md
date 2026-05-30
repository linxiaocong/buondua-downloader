# OpenClaw Buondua Album Downloader Skill

An autonomous, robust, and highly optimized **OpenClaw Skill** designed to download entire high-resolution photosets from `buondua.com`. 

The skill is built using **Python** and **Playwright** to navigate multi-page galleries, trigger lazy-loaded images, filter out layout components, and safely download photos without triggering Cloudflare blocks.

---

## Key Features

* 🎯 **Precise Container Targeting**: Restricts the image extraction queries specifically to the `.article-fulltext` wrapper. This guarantees that only the photoset's main images are downloaded, completely filtering out unrelated recommended album covers, sidebars, or header/footer graphics.
* 🛡️ **Self-Healing Design**: Uses container-targeting as the primary query selector, but gracefully falls back to `document` with physical dimension-based scanning in case the website updates its HTML container class names.
* 📏 **Physical Dimension Filtering**: Evaluates elements' physical properties (`naturalWidth` and `naturalHeight` >= 300px) in the DOM in real-time. This eliminates UI layout assets, logos, and thumbnails dynamically.
* 🔄 **Dynamic Pagination Mapping**: Automatically discovers, parses, and sorts page links sequentially (resolving `?page=X` or `/page/X` structures) to process multi-page galleries seamlessly.
* 📜 **Lazy-Loading Scrolling**: Simulates realistic browsing by scrolling down incrementally in 80% viewport steps to trigger the full load events of lazy-loaded photos before extraction.
* 🌐 **Bypassing Cloudflare Checks**: Downloads image binary streams using Playwright's browser network request pipeline (`page.request.get`). This automatically inherits active cookies, user-agents, and session headers, avoiding `403 Forbidden` blockages.
* 🔤 **International Unicode Support**: Reconfigures standard IO streams on startup to support UTF-8, ensuring that album titles containing localized international characters (e.g., Korean, Japanese, Chinese) compile and create folders cleanly on Windows/Unix without raising `UnicodeEncodeError`.

---

## Skill File Structure

```text
buondua-downloader/
├── SKILL.md              # OpenClaw skill manifest & agent playbook
├── README.md             # Setup and developer documentation
├── requirements.txt      # Python dependencies
└── scripts/
    └── download_album.py # Core Python/Playwright crawler script
```

---

## Installation

### 1. Install Python Dependencies
Install Playwright and its runtime packages:
```bash
pip install -r requirements.txt
```

### 2. Set Up Playwright Browser Binaries
Initialize the required Chromium browser binary:
```bash
playwright install chromium
```

---

## Usage Guide

To download all photos in an album, invoke the core scraper script by providing the album URL and a target directory:

```bash
python scripts/download_album.py "<album-url>" -o "<destination-parent-folder>"
```

### Command Line Arguments

| Argument | Long Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `url` | (Positional) | *Required* | The exact URL of the buondua.com album. |
| `-o` | `--output-dir` | `./downloads` | The parent folder to save photos. A subfolder named after the album title will be automatically created inside this directory. |
| (None) | `--no-headless` | Headless | Launch Playwright with a visible browser window (useful for debugging/manual verification). |
| (None) | `--scroll-delay` | `0.5` | Delay in seconds between incremental scroll steps. |
| (None) | `--download-delay` | `0.3` | Delay in seconds between image downloads (prevents server overload). |
| (None) | `--timeout` | `30000` | Browser navigation timeout in milliseconds. |

### Execution Example

```bash
python scripts/download_album.py "https://buondua.com/ag-674-yeonyu-yeon-yu-148-photos-6-videos-ac163970f88e474f688ed3ecbd99709c-54758" -o "./downloads"
```

*This command automatically traverses all pages of the album, clean-scrolls to trigger lazy loading, resolves the exact 148 photos, and saves them sequentially as `001.jpeg` through `148.jpeg` in your `./downloads` folder.*

---

## License

Distributed under the **Apache-2.0** License. See `SKILL.md` for more details.
