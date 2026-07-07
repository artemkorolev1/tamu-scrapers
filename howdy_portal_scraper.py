#!/usr/bin/env python3
"""
Standalone requests-based scraper for howdyportal.tamu.edu
Downloads course section data and syllabi PDFs for specified departments and terms.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

PORTAL_URL = "https://howdyportal.tamu.edu/uPortal/p/public-class-search-ui.ctf1/max/render.uP"
TERMS_API = "https://howdyportal.tamu.edu/api/all-terms"
SECTIONS_API = "https://howdyportal.tamu.edu/api/course-sections"
SYLLABUS_PDF_API = "https://howdyportal.tamu.edu/api/course-syllabus-pdf"

USER_AGENT = "TAMU-Student-Project-Research"

DEFAULT_DEPTS = "CSCE,ISEN,STAT,ECEN"
DEFAULT_TERMS = "202611,202621,202631"

TERM_CODE_LABELS = {
    "202511": "Spring_2025",
    "202521": "Summer_2025",
    "202531": "Fall_2025",
    "202611": "Spring_2026",
    "202621": "Summer_2026",
    "202631": "Fall_2026",
    "202711": "Spring_2027",
    "202721": "Summer_2027",
    "202731": "Fall_2027",
}


def term_label(term_code: str) -> str:
    """202611 -> Spring_2026, falls back to raw code if not in map."""
    if term_code in TERM_CODE_LABELS:
        return TERM_CODE_LABELS[term_code]
    # Generic fallback: last two digits encode semester
    year = term_code[:4]
    suffix = term_code[4:]
    sem_map = {"11": "Spring", "21": "Summer", "31": "Fall"}
    sem = sem_map.get(suffix, f"Term{suffix}")
    return f"{sem}_{year}"


def parse_args():
    p = argparse.ArgumentParser(description="Scrape course data from howdyportal.tamu.edu")
    p.add_argument("--depts", default=None, help="Comma-separated department codes")
    p.add_argument("--terms", default=None, help="Comma-separated term codes (e.g. 202611)")
    p.add_argument("--all-departments", action="store_true", help="Scrape all departments (ignores --depts)")
    p.add_argument("--output-dir", default=None, help="Output directory")
    p.add_argument("--delay", type=float, default=None, help="Seconds between PDF downloads")
    p.add_argument("--no-graduate", action="store_true", help="Include all course levels (not just >= 600)")
    return p.parse_args()


def get_config(args):
    depts_raw = args.depts or os.getenv("DEPARTMENTS", DEFAULT_DEPTS)
    terms_raw = args.terms or os.getenv("TARGET_TERMS", DEFAULT_TERMS)
    graduate_only_env = os.getenv("GRADUATE_ONLY", "true").lower() == "true"
    return {
        "departments": [d.strip() for d in depts_raw.split(",") if d.strip()],
        "all_departments": args.all_departments,
        "target_terms": [t.strip() for t in terms_raw.split(",") if t.strip()],
        "graduate_only": graduate_only_env and not args.no_graduate,
        "delay": args.delay if args.delay is not None else float(os.getenv("DOWNLOAD_DELAY", "2.0")),
        "output_dir": Path(args.output_dir or os.getenv("OUTPUT_DIR", "./output")),
    }


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def establish_session(session: requests.Session):
    """GET the portal page to establish cookies."""
    try:
        resp = session.get(PORTAL_URL, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Warning: could not seed session from portal page: {e}")


def fetch_available_terms(session: requests.Session) -> list[dict]:
    resp = session.get(TERMS_API, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # API may return list directly or nested under a key
    if isinstance(data, list):
        return data
    return data.get("terms", data.get("data", []))


def fetch_sections(session: requests.Session, term_code: str) -> list[dict]:
    payload = {"termCode": term_code}
    resp = session.post(SECTIONS_API, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("sections", data.get("data", data.get("results", [])))


def _sget(section: dict, *keys: str) -> str:
    """Return the first non-empty value from a list of field names."""
    for k in keys:
        v = section.get(k)
        if v:
            return str(v)
    return ""


def course_number(section: dict) -> int:
    """Extract numeric course number from a section record."""
    raw = _sget(
        section, "SWV_CLASS_SEARCH_COURSE", "courseNumber",
        "COURSE_NUMBER", "course_number", "course",
    )
    digits = "".join(c for c in raw if c.isdigit())
    return int(digits) if digits else 0


def section_subject(section: dict) -> str:
    raw = _sget(
        section, "SWV_CLASS_SEARCH_SUBJECT", "subject",
        "SUBJECT", "subjectCode",
    )
    return raw.upper()


def section_campus(section: dict) -> str:
    return _sget(
        section, "SWV_CLASS_SEARCH_SITE", "campus",
        "CAMPUS", "campusDescription",
    )


def section_crn(section: dict) -> str:
    return _sget(
        section, "SWV_CLASS_SEARCH_CRN", "crn",
        "CRN", "courseReferenceNumber",
    )


def section_course_num_str(section: dict) -> str:
    return _sget(
        section, "SWV_CLASS_SEARCH_COURSE", "courseNumber",
        "COURSE_NUMBER", "course_number", "course",
    )


def section_section_str(section: dict) -> str:
    return _sget(
        section, "SWV_CLASS_SEARCH_SECTION", "sectionNumber",
        "SECTION", "section",
    )


def section_title(section: dict) -> str:
    return _sget(
        section, "SWV_CLASS_SEARCH_TITLE", "courseTitle",
        "COURSE_TITLE", "title",
    )


def section_instructor(section: dict) -> str:
    raw = _sget(
        section, "SWV_CLASS_SEARCH_INSTRCTR_JSON", "instructor",
        "INSTRUCTOR", "instructorName",
    )
    try:
        parsed = json.loads(raw) if raw.startswith("[") or raw.startswith("{") else raw
        if isinstance(parsed, list):
            return ", ".join(str(i.get("name") or i.get("displayName") or i) for i in parsed)
    except (json.JSONDecodeError, AttributeError):
        pass
    return raw


def has_syllabus(section: dict) -> bool:
    return _sget(
        section, "SWV_CLASS_SEARCH_HAS_SYL_IND", "hasSyllabus", "has_syllabus",
    ).upper() == "Y"


def filter_sections(sections: list[dict], cfg: dict) -> list[dict]:
    out = []
    for s in sections:
        if "College Station" not in section_campus(s):
            continue
        if not cfg["all_departments"] and section_subject(s) not in cfg["departments"]:
            continue
        if cfg["graduate_only"] and course_number(s) < 600:
            continue
        out.append(s)
    return out


def section_to_record(section: dict, term_code: str) -> dict:
    return {
        "term_code": term_code,
        "crn": section_crn(section),
        "title": section_title(section),
        "subject": section_subject(section),
        "course": section_course_num_str(section),
        "section": section_section_str(section),
        "instructor": section_instructor(section),
        "raw_data": section,
    }


def pdf_filename(term_code: str, record: dict) -> str:
    subj = record["subject"]
    course = record["course"]
    sec = record["section"]
    crn = record["crn"]
    return f"{term_code}_{subj}_{course}_{sec}_{crn}.pdf"


def download_syllabus_pdf(
    session: requests.Session,
    term_code: str,
    crn: str,
    out_path: Path,
    delay: float,
) -> bool:
    if out_path.exists():
        return True

    url = f"{SYLLABUS_PDF_API}?termCode={term_code}&crn={crn}"
    try:
        resp = session.get(url, timeout=60, stream=True)
        if resp.status_code == 404:
            tqdm.write(f"  No PDF found for CRN {crn} in term {term_code}")
            return False
        resp.raise_for_status()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)

        time.sleep(delay)
        return True
    except requests.RequestException as e:
        tqdm.write(f"  PDF download failed for CRN {crn}: {e}")
        return False


def save_data_json(out_dir: Path, records: list[dict]):
    out_dir.mkdir(parents=True, exist_ok=True)
    # Merge with any existing records (resumable)
    data_file = out_dir / "data.json"
    existing: list[dict] = []
    if data_file.exists():
        try:
            existing = json.loads(data_file.read_text())
        except json.JSONDecodeError:
            existing = []

    existing_crns = {r["crn"] for r in existing}
    new_records = [r for r in records if r["crn"] not in existing_crns]
    combined = existing + new_records
    data_file.write_text(json.dumps(combined, indent=2))
    return len(new_records)


def main():
    args = parse_args()
    cfg = get_config(args)

    print(f"Departments : {'ALL' if cfg['all_departments'] else cfg['departments']}")
    print(f"Terms       : {cfg['target_terms']}")
    print(f"Graduate    : {cfg['graduate_only']}")
    print(f"Output      : {cfg['output_dir']}")
    print()

    session = make_session()

    try:
        print("Establishing session with Howdy portal…")
        establish_session(session)

        print("Fetching available terms…")
        try:
            available = fetch_available_terms(session)
            available_codes = {str(t.get("termCode") or t.get("code") or "") for t in available}
            print(f"  Available terms: {sorted(available_codes)}")
        except Exception as e:
            print(f"  Warning: could not fetch term list: {e}")
            available_codes = set()

        for term_code in tqdm(cfg["target_terms"], desc="Terms", unit="term"):
            if available_codes and term_code not in available_codes:
                tqdm.write(f"  Term {term_code} not in available terms, skipping")
                continue

            tqdm.write(f"\nFetching sections for term {term_code}…")
            try:
                raw_sections = fetch_sections(session, term_code)
            except requests.RequestException as e:
                tqdm.write(f"  Error fetching sections for {term_code}: {e}")
                continue

            tqdm.write(f"  Got {len(raw_sections)} total sections")
            filtered = filter_sections(raw_sections, cfg)
            tqdm.write(f"  {len(filtered)} sections after filtering")

            # Group by subject for organized output
            by_subject: dict[str, list[dict]] = {}
            for s in filtered:
                subj = section_subject(s)
                by_subject.setdefault(subj, []).append(s)

            for subj, sections in tqdm(by_subject.items(), desc=f"  {term_code} subjects", unit="dept", leave=False):
                tlabel = term_label(term_code)
                out_dir = cfg["output_dir"] / "howdy_portal" / subj / "graduate" / tlabel

                records = [section_to_record(s, term_code) for s in sections]
                new_count = save_data_json(out_dir, records)
                tqdm.write(f"    {subj}: {len(records)} sections ({new_count} new) -> {out_dir}/data.json")

                # Download PDFs for sections that have one
                pdf_sections = [s for s in sections if has_syllabus(s)]
                if pdf_sections:
                    tqdm.write(f"    {subj}: {len(pdf_sections)} sections with syllabus PDFs")
                    for s in tqdm(pdf_sections, desc=f"    PDFs {subj}", unit="pdf", leave=False):
                        rec = section_to_record(s, term_code)
                        fname = pdf_filename(term_code, rec)
                        out_path = out_dir / fname
                        download_syllabus_pdf(session, term_code, rec["crn"], out_path, cfg["delay"])

        print("\nDone.")

    except KeyboardInterrupt:
        print("\nInterrupted by user. Partial results saved.")
        sys.exit(0)


if __name__ == "__main__":
    main()
