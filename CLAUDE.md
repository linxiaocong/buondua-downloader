# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this project is

An **OpenClaw Skill** that downloads complete photo albums from `buondua.com`. It is a
single-purpose scraper: one Python/Playwright script plus the skill manifest and docs that
describe how an agent should invoke it. There is no package, no module hierarchy, and no
build step — the script is run directly.

```text
buondua-downloader/
├── SKILL.md                  # OpenClaw skill manifest (YAML frontmatter + agent playbook)
├── README.md                 # Human-facing setup & usage docs
├── CLAUDE.md                 # This file
├── requirements.txt          # Single dep: playwright>=1.40.0
├── LICENSE                   # GPLv3
└── scripts/
    └── download_album.py     # The entire implementation (~415 lines)
```

## Setup & running

```bash
pip install -r requirements.txt
playwright install chromium          # required; the script launches real Chromium

python scripts/download_album.py "<album-url>" -o "./downloads"
```

Useful flags while developing: `--no-headless` (watch the browser), `--scroll-delay`,
`--download-delay`, `--timeout` (ms). Defaults live in `main()` at
`scripts/download_album.py:400`.

Note for sandboxed/CI environments where Chromium is preinstalled (e.g. Claude Code on the
web): `PLAYWRIGHT_BROWSERS_PATH` is already set — do **not** run `playwright install`, and
if a pinned Playwright version can't find the binary, pass
`executable_path="/opt/pw-browsers/chromium"` to `chromium.launch()` rather than downloading.

## Architecture: the scrape pipeline

Everything is async (`asyncio` + `playwright.async_api`) and lives in one file. Read
`run_downloader()` (`scripts/download_album.py:240`) top-to-bottom — it is the orchestrator
and the pipeline order matters:

1. **Browser setup** — Chromium with a fixed desktop UA (`DEFAULT_USER_AGENT`, line 26) and
   a 1920x1080 viewport. The UA and viewport are load-bearing: the site serves different
   markup to mobile/unknown agents.
2. **Title extraction** — first `<h1>` becomes the album folder name, sanitized by
   `clean_filename()` (line 29). Falls back to `"Buondua Album"`.
3. **Canonical URL resolution** (line 289) — the server normalizes special characters in
   album slugs, so a user-supplied URL may not match the `href`s in the page's own
   pagination links. The `<link rel="canonical">` value (minus any `?page=N`) is used as the
   base for pagination matching. **Don't remove this** — it was the fix in commit `ba1739a`.
4. **Pagination mapping** — `extract_pagination_urls()` (line 167) scans every `<a>` on the
   *first* page, keeps same-host links whose path matches the album base, and accepts either
   `?page=N` / `?p=N` query forms or `/N`, `/page/N` path forms. Both sides are
   percent-decoded before comparison (Unicode slugs). Sorted by `extract_page_number()`.
5. **Lazy-load scrolling** — `scroll_page_to_trigger_lazy_load()` (line 66) steps down in
   80%-viewport increments, re-reading `document.body.scrollHeight` each step (the page
   grows as images load), then bottom, then back to top.
6. **Image extraction** — `get_page_images()` (line 93) runs one batched
   `page.evaluate()` to pull `src`, lazy-load data attributes, and `naturalWidth/Height` for
   every `<img>` in a single round-trip.
7. **Download** — a single background worker consumes an `asyncio.Queue`, writing
   `001.jpg`, `002.jpg`, … into the album folder.

## Invariants — do not "improve" these without cause

These are deliberate design choices, several of them hard-won against the site's defenses:

- **Downloads go through `page.request.get()`** (`download_image()`, line 213), not
  `requests`/`httpx`/`aiohttp`. The Playwright request context inherits the live session's
  cookies, TLS fingerprint, and headers, which is what avoids `403 Forbidden` from
  Cloudflare. Swapping in a plain HTTP client will silently break downloading. `requirements.txt`
  intentionally has exactly one dependency.
- **`.article-fulltext` is the primary container, `document` is the fallback** (line 101).
  The container scoping is what excludes recommended-album covers and sidebars; the fallback
  keeps the script alive if the site renames the class.
- **The 300x300 `naturalWidth`/`naturalHeight` threshold** (line 151) is the second filter
  layer. When dimensions read as `0` (unloaded/hidden), it falls back to URL substring
  matching against `logo`/`avatar`/`icon`/`banner`/`theme`/`nav`/`loader`.
- **Downloads are sequential, one worker, with a delay between each** (lines 326–357). This
  is politeness/rate-limit avoidance, not an oversight. Don't parallelize into N workers
  without a deliberate decision — and note the worker shares the single `page` object with
  the navigation loop.
- **Queue shutdown order**: `await queue.join()` → put `None` sentinel → `await worker_task`.
  Keep that order; reversing it deadlocks or drops trailing downloads.
- **UTF-8 stdio reconfiguration at import time** (lines 14–23). Album titles are frequently
  Korean/Japanese/Chinese; without this, Windows terminals raise `UnicodeEncodeError` before
  anything useful happens.
- **Failures degrade, they don't abort.** Nearly every network/DOM step is wrapped in
  `try/except` that logs and continues (initial navigation, title, canonical URL, per-page
  load). A partial album beats a stack trace. Preserve that posture.

## Conventions

- **Python 3.11+**, stdlib + Playwright only. No type hints, no dataclasses, no framework —
  match the existing plain-function style.
- **Async everywhere.** New network/DOM helpers should be `async def` and take `page` as
  their first argument.
- **Logging is `print()` with a status prefix**: `[+]` for progress/success, `[-]` for
  failures and fallbacks. There is no `logging` setup; don't introduce one for a small change.
- **Docstrings** are short triple-quoted summaries on every function. Inline comments explain
  *why* (especially anti-bot workarounds), not *what*.
- **Prefer one batched `page.evaluate()`** over per-element `await`s when reading many DOM
  properties — see `get_page_images()`.

## Making changes

- **Three places document the CLI.** Any change to arguments or defaults must be mirrored in
  `main()` (`scripts/download_album.py:400`), the "Script Arguments" section of `SKILL.md`,
  and the argument table in `README.md`. They currently agree; keep them that way.
- **`SKILL.md` frontmatter** (`name`, `description`, `license`, `metadata.version`) is the
  OpenClaw manifest. Bump `metadata.version` for behavioral changes to the skill contract.
- **No tests, no linter, no CI.** Verification is manual: run the script against a real album
  URL and check the page count, the resolved image count, and that the files on disk are
  full-resolution photos rather than thumbnails. `--no-headless` plus a small album is the
  fastest feedback loop. Selector- or filter-related changes *must* be exercised against a
  live page — nothing in this repo can catch a broken selector statically.
- **Commit style** in history is terse (`fix`, `enhance`). Prefer a clearer subject line for
  new work; there's no enforced convention to follow.

## Known rough edges

Worth knowing before you're asked to change something nearby — none are currently bugs the
user has asked to fix, so raise them rather than silently rewriting:

- **License is inconsistent across files.** `LICENSE` is GPLv3, `README.md` says GPLv3, but
  the `license:` field in `SKILL.md` frontmatter says `Apache-2.0`. Ask which is intended
  before changing any of them.
- **Pagination is discovered only from the first page.** If the site ever truncates its
  pager (`1 2 3 … 10`), later pages would be missed. Currently all page links are rendered,
  so it works.
- **`Referer` is always the originally supplied `url`**, not the page the image was found on
  (line 345). Fine today; relevant if the site tightens referer checks.
- **File extensions come from the image URL**, so an album can end up with mixed
  `.jpg`/`.jpeg`/`.png`. `README.md`'s example claims uniform `.jpeg`, which is incidental.
- **Numbering is assigned at parse time**, so a failed download leaves a gap in the sequence
  rather than renumbering.

## Scope

This tool scrapes a public gallery site. Keep changes within that purpose: album discovery,
extraction reliability, download robustness, and politeness toward the server. Increasing
request concurrency or removing the inter-download delays works against the last of those.
