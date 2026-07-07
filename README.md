# TAMU Course & Syllabus Scrapers

Standalone Python scrapers for collecting Texas A&M course data and syllabi for academic research purposes.
No TAMUBOT or internal dependencies — runs on any machine with Python 3.10+.

## Scrapers

| Script | Source | Method | Output |
|---|---|---|---|
| `simple_syllabus_scraper.py` | tamu.simplesyllabus.com | Playwright (headless Chromium) | PDF syllabi |
| `howdy_portal_scraper.py` | howdyportal.tamu.edu | requests (HTTP) | JSON + PDF syllabi |

---

## Prerequisites

**Python 3.10+** is required.

```bash
pip install -r requirements.txt
playwright install chromium   # only needed for simple_syllabus_scraper.py
```

Copy `.env.example` to `.env` and edit as needed (all settings also have CLI flags):

```bash
cp .env.example .env
```

---

## simple_syllabus_scraper.py

Scrapes PDF syllabi from [tamu.simplesyllabus.com](https://tamu.simplesyllabus.com) using a headless Chromium browser.

### Usage

```bash
# Default: CSCE, ISEN, STAT, ECEN — Spring/Summer/Fall 2026 — graduate only
python simple_syllabus_scraper.py

# Custom departments and terms
python simple_syllabus_scraper.py --depts CSCE,ECEN --terms "Spring 2026,Fall 2026"

# Preview matches without downloading
python simple_syllabus_scraper.py --dry-run

# Custom output directory, slower requests
python simple_syllabus_scraper.py --output-dir /data/syllabi --delay 2.0

# Cap total download at 500 MB
python simple_syllabus_scraper.py --max-mb 500
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--depts` | `CSCE,ISEN,STAT,ECEN` | Comma-separated department codes |
| `--terms` | `Spring 2026,Summer 2026,Fall 2026` | Comma-separated term names |
| `--dry-run` | off | Print matches without downloading PDFs |
| `--output-dir` | `./output` | Root directory for output |
| `--delay` | `1.0` | Seconds between requests |
| `--max-retries` | `5` | Max retry attempts on errors |
| `--max-mb` | `0` (unlimited) | Stop after this many MB downloaded |

### Output structure

```
output/
└── simple_syllabus/
    └── CSCE/
        └── graduate/
            └── Spring_2026/
                ├── 3a9c109e_CSCE_625_500_12345.pdf
                ├── 3a9c109e_CSCE_689_200_67890.pdf
                └── metadata.json
```

`metadata.json` maps each filename to `doc_id` and `syllabus_url`.

### Supported terms

| Term name | Term ID prefix |
|---|---|
| Summer 2025 | `9ca19ce6` |
| Fall 2025 | `ecd304d6` |
| Spring 2026 | `3a9c109e` |
| Summer 2026 | `1da0b525` |
| Fall 2026 | `6dcfa515` |

---

## howdy_portal_scraper.py

Scrapes course section data from [howdyportal.tamu.edu](https://howdyportal.tamu.edu) using plain HTTP requests.
Downloads syllabus PDFs for sections where one is available (`SWV_CLASS_SEARCH_HAS_SYL_IND == "Y"`).

### Usage

```bash
# Default: CSCE, ISEN, STAT, ECEN — terms 202611, 202621, 202631 — graduate only
python howdy_portal_scraper.py

# Custom departments and terms
python howdy_portal_scraper.py --depts CSCE,ECEN --terms 202611,202631

# Include undergraduate courses
python howdy_portal_scraper.py --no-graduate

# Scrape every department (ignores --depts)
python howdy_portal_scraper.py --all-departments

# Custom output and download delay
python howdy_portal_scraper.py --output-dir /data/howdy --delay 3.0
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--depts` | `CSCE,ISEN,STAT,ECEN` | Comma-separated department codes |
| `--terms` | `202611,202621,202631` | Comma-separated term codes |
| `--all-departments` | off | Ignore `--depts`, scrape everything |
| `--output-dir` | `./output` | Root directory for output |
| `--delay` | `2.0` | Seconds between PDF downloads |
| `--no-graduate` | off | Include undergraduate courses (< 600) |

### Output structure

```
output/
└── howdy_portal/
    └── CSCE/
        └── graduate/
            └── Spring_2026/
                ├── data.json
                ├── 202611_CSCE_625_500_12345.pdf
                └── 202611_CSCE_689_200_67890.pdf
```

`data.json` is an array of objects:

```json
[
  {
    "term_code": "202611",
    "crn": "12345",
    "title": "Machine Learning",
    "subject": "CSCE",
    "course": "625",
    "section": "500",
    "instructor": "Smith, John",
    "raw_data": { ... }
  }
]
```

### Term code reference

| Term code | Term name |
|---|---|
| `202511` | Spring 2025 |
| `202521` | Summer 2025 |
| `202531` | Fall 2025 |
| `202611` | Spring 2026 |
| `202621` | Summer 2026 |
| `202631` | Fall 2026 |

---

## Environment variable reference

All options can be set in `.env` (copy from `.env.example`) or overridden with CLI flags.

| Variable | Applies to | Default | Description |
|---|---|---|---|
| `DEPARTMENTS` | both | `CSCE,ISEN,STAT,ECEN` | Comma-separated subject codes |
| `TARGET_TERMS` | both | see scrapers | Term names (simple syllabus) or codes (howdy) |
| `GRADUATE_ONLY` | both | `true` | Only courses numbered 600+ |
| `OUTPUT_DIR` | both | `./output` | Root output directory |
| `DELAY` | simple_syllabus | `1.0` | Seconds between requests |
| `MAX_RETRIES` | simple_syllabus | `5` | Retry attempts on HTTP errors |
| `MAX_MB` | simple_syllabus | `0` | Download cap in MB (0 = unlimited) |
| `DOWNLOAD_DELAY` | howdy_portal | `2.0` | Seconds between PDF downloads |

---

## Resumability

Both scrapers are resumable:
- **simple_syllabus**: skips PDFs that already exist on disk.
- **howdy_portal**: skips existing PDFs and merges new section records into existing `data.json`.

Re-run the same command after an interruption and it will pick up where it left off.
