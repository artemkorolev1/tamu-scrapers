#!/usr/bin/env python3
"""
Standalone Playwright scraper for tamu.simplesyllabus.com
Downloads graduate course syllabi as PDFs for the specified departments and terms.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tqdm import tqdm

load_dotenv()

LIBRARY_URL = "https://tamu.simplesyllabus.com/en-US/syllabus-library"
SEARCH_API = "https://tamu.simplesyllabus.com/api2/doc-library-search"

TERM_IDS = {
    "Summer 2025": "9ca19ce6-f1a3-4b2e-8f3d-1a2b3c4d5e6f",
    "Fall 2025":   "ecd304d6-a2b3-4c5d-9e0f-1a2b3c4d5e6f",
    "Spring 2026": "3a9c109e-b3c4-4d5e-af10-2b3c4d5e6f7a",
    "Summer 2026": "1da0b525-c4d5-4e6f-b021-3c4d5e6f7a8b",
    "Fall 2026":   "6dcfa515-d5e6-4f70-c132-4d5e6f7a8b9c",
}

TITLE_RE = re.compile(
    r"^(?P<subject>[A-Z]+)\s+(?P<course>\d+)\s+(?P<section>\S+)\s+\((?P<crn>\d+)\)$"
)

DEFAULT_DEPTS = "CSCE,ISEN,STAT,ECEN"
DEFAULT_TERMS = "Spring 2026,Summer 2026,Fall 2026"


def parse_args():
    p = argparse.ArgumentParser(description="Scrape syllabi from tamu.simplesyllabus.com")
    p.add_argument("--depts", default=None, help="Comma-separated department codes")
    p.add_argument("--terms", default=None, help="Comma-separated term names")
    p.add_argument("--dry-run", action="store_true", help="List matches without downloading")
    p.add_argument("--output-dir", default=None, help="Output directory")
    p.add_argument("--delay", type=float, default=None, help="Seconds between requests")
    p.add_argument("--max-retries", type=int, default=None, help="Max retry attempts")
    p.add_argument("--max-mb", type=float, default=None, help="Max total MB (0=unlimited)")
    return p.parse_args()


def get_config(args):
    depts_raw = args.depts or os.getenv("DEPARTMENTS", DEFAULT_DEPTS)
    terms_raw = args.terms or os.getenv("TARGET_TERMS", DEFAULT_TERMS)
    return {
        "departments": [d.strip() for d in depts_raw.split(",") if d.strip()],
        "target_terms": [t.strip() for t in terms_raw.split(",") if t.strip()],
        "graduate_only": os.getenv("GRADUATE_ONLY", "true").lower() == "true",
        "delay": args.delay if args.delay is not None else float(os.getenv("DELAY", "1.0")),
        "max_retries": args.max_retries if args.max_retries is not None else int(os.getenv("MAX_RETRIES", "5")),
        "max_mb": args.max_mb if args.max_mb is not None else float(os.getenv("MAX_MB", "0")),
        "output_dir": Path(args.output_dir or os.getenv("OUTPUT_DIR", "./output")),
        "dry_run": args.dry_run,
    }


def term_label(term_name: str) -> str:
    """'Spring 2026' -> 'Spring_2026'"""
    return term_name.replace(" ", "_")


def seed_session(page):
    """Visit the library page to set cookies/session before API calls."""
    page.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(1.5)


def fetch_page(page, dept: str, term_id: str, page_num: int, cfg: dict) -> dict | None:
    """
    Fetch one search result page. Returns parsed JSON or None on unrecoverable error.
    Re-seeds session on 403/500 and retries with exponential backoff.
    """
    params = {
        "search": dept,
        "term_ids[]": term_id,
        "page": page_num,
        "page_size": 50,
    }
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    url = f"{SEARCH_API}?{query}"

    for attempt in range(cfg["max_retries"]):
        try:
            response = page.request.get(url, timeout=30_000)
            if response.status == 200:
                return response.json()
            if response.status in (403, 500):
                wait = 2 ** attempt
                tqdm.write(f"  HTTP {response.status} on attempt {attempt+1}, re-seeding in {wait}s…")
                time.sleep(wait)
                seed_session(page)
                continue
            tqdm.write(f"  Unexpected HTTP {response.status} for {dept}, page {page_num}")
            return None
        except PlaywrightTimeoutError:
            wait = 2 ** attempt
            tqdm.write(f"  Timeout on attempt {attempt+1}, retrying in {wait}s…")
            time.sleep(wait)
        except Exception as e:
            tqdm.write(f"  Error on attempt {attempt+1}: {e}")
            time.sleep(2 ** attempt)

    tqdm.write(f"  Giving up on {dept} page {page_num} after {cfg['max_retries']} attempts")
    return None


def collect_matches(page, dept: str, cfg: dict) -> list[dict]:
    """Return all matching syllabus records for one department across all target terms."""
    matches = []
    for term_name in cfg["target_terms"]:
        term_id = TERM_IDS.get(term_name)
        if not term_id:
            tqdm.write(f"  Unknown term '{term_name}', skipping")
            continue

        page_num = 1
        while True:
            data = fetch_page(page, dept, term_id, page_num, cfg)
            if data is None:
                break

            results = data.get("results", [])
            if not results:
                break

            for doc in results:
                title = (doc.get("title") or "").strip()
                m = TITLE_RE.match(title)
                if not m:
                    continue

                subject = m.group("subject")
                course = int(m.group("course"))
                section = m.group("section")
                crn = m.group("crn")

                location = doc.get("location") or ""
                if "College Station" not in location:
                    continue
                if subject not in cfg["departments"]:
                    continue
                if cfg["graduate_only"] and course < 600:
                    continue

                matches.append({
                    "term_name": term_name,
                    "term_id": term_id,
                    "subject": subject,
                    "course": course,
                    "section": section,
                    "crn": crn,
                    "doc_id": doc.get("id") or doc.get("doc_id") or "",
                    "code": doc.get("code") or doc.get("slug") or doc.get("id") or "",
                    "slug": doc.get("slug") or doc.get("code") or "",
                    "title": title,
                    "location": location,
                })

            total = data.get("total", 0)
            if page_num * 50 >= total:
                break
            page_num += 1
            time.sleep(cfg["delay"])

    return matches


def pdf_path(cfg: dict, match: dict) -> Path:
    subj = match["subject"]
    term_label_str = term_label(match["term_name"])
    fname = (
        f"{match['term_id'][:8]}_{subj}_{match['course']}_{match['section']}_{match['crn']}.pdf"
    )
    return cfg["output_dir"] / "simple_syllabus" / subj / "graduate" / term_label_str / fname


def download_pdf(page, match: dict, out_path: Path, cfg: dict) -> bool:
    """Open view page and print to PDF. Returns True on success."""
    code = match["code"]
    slug_enc = quote(match["slug"], safe="")
    view_url = f"https://tamu.simplesyllabus.com/en-US/doc/{code}/{slug_enc}?mode=view"

    for attempt in range(cfg["max_retries"]):
        try:
            page.goto(view_url, wait_until="networkidle", timeout=60_000)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.pdf(path=str(out_path), format="Letter", print_background=True)
            return True
        except PlaywrightTimeoutError:
            wait = 2 ** attempt
            tqdm.write(f"  PDF timeout attempt {attempt+1}, retrying in {wait}s…")
            time.sleep(wait)
            seed_session(page)
        except Exception as e:
            tqdm.write(f"  PDF error attempt {attempt+1}: {e}")
            time.sleep(2 ** attempt)

    return False


def update_metadata(out_dir: Path, match: dict, out_path: Path):
    meta_file = out_dir / "metadata.json"
    meta: dict = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
        except json.JSONDecodeError:
            meta = {}

    meta[out_path.name] = {
        "doc_id": match["doc_id"],
        "syllabus_url": (
            f"https://tamu.simplesyllabus.com/en-US/doc/{match['code']}/{match['slug']}?mode=view"
        ),
    }
    meta_file.write_text(json.dumps(meta, indent=2))


def bytes_used(cfg: dict) -> float:
    root = cfg["output_dir"] / "simple_syllabus"
    if not root.exists():
        return 0.0
    return sum(f.stat().st_size for f in root.rglob("*.pdf")) / (1024 * 1024)


def main():
    args = parse_args()
    cfg = get_config(args)

    print(f"Departments : {cfg['departments']}")
    print(f"Terms       : {cfg['target_terms']}")
    print(f"Graduate    : {cfg['graduate_only']}")
    print(f"Output      : {cfg['output_dir']}")
    print(f"Dry run     : {cfg['dry_run']}")
    print()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            print("Seeding session…")
            seed_session(page)

            all_matches: list[dict] = []
            for dept in tqdm(cfg["departments"], desc="Collecting", unit="dept"):
                matches = collect_matches(page, dept, cfg)
                all_matches.extend(matches)
                tqdm.write(f"  {dept}: {len(matches)} matches")
                time.sleep(cfg["delay"])

            print(f"\nTotal matches: {len(all_matches)}")

            if cfg["dry_run"]:
                for m in all_matches:
                    print(f"  {m['term_name']} | {m['subject']} {m['course']} {m['section']} ({m['crn']})")
                browser.close()
                return

            downloaded = 0
            skipped = 0
            failed = 0

            for match in tqdm(all_matches, desc="Downloading", unit="pdf"):
                if cfg["max_mb"] > 0 and bytes_used(cfg) >= cfg["max_mb"]:
                    tqdm.write(f"Reached {cfg['max_mb']} MB limit, stopping.")
                    break

                out_path = pdf_path(cfg, match)
                if out_path.exists():
                    skipped += 1
                    continue

                ok = download_pdf(page, match, out_path, cfg)
                if ok:
                    update_metadata(out_path.parent, match, out_path)
                    downloaded += 1
                else:
                    failed += 1

                time.sleep(cfg["delay"])

            browser.close()

        print(f"\nDone. Downloaded={downloaded}, Skipped={skipped}, Failed={failed}")

    except KeyboardInterrupt:
        print("\nInterrupted by user. Partial results saved.")
        sys.exit(0)


if __name__ == "__main__":
    main()
