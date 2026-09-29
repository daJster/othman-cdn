"""
QuranFlash EDITIONS Book Scraper
================================
Scrapes pages: https://app.quranflash.com/book/EDITION?en#/reader/chapter/NUMBER
Number range: 1 to 603, odd numbers only

Outputs (in ./dist/):
  - book_EDITION.csv
  - book_EDITION_bbox.json
"""

import asyncio
import csv
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from tqdm.asyncio import tqdm

# ─── Config ──────────────────────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass(frozen=True)
class Edition:
    name: str
    last_chapter: int
    slug: str


EDITIONS = (
    Edition(name="Tajweed", last_chapter=604, slug="Tajweed"),
    Edition(name="MedinaOld", last_chapter=605, slug="MedinaOld"),
    Edition(name="Warsh1", last_chapter=559, slug="Warsh1"),
)

DEFAULT_EDITION = 2  # index into EDITIONS

_active = EDITIONS[DEFAULT_EDITION]

BASE_URL = (
    f"https://app.quranflash.com/book/{_active.slug}?en#/reader/chapter/{{number}}"
)
IMG_PREFIX = "https://app.quranflash.com/"
CHAPTERS = list(range(1, _active.last_chapter, 2))  # odd numbers
SPREAD_IDS = ["spreadL", "spreadR"]

OUTPUT_DIR = Path("dist")
CSV_FILE = OUTPUT_DIR / f"book_{_active.slug}.csv"
JSON_FILE = OUTPUT_DIR / f"book_{_active.slug}_bbox.json"

PAGE_TIMEOUT = 30_000
CONTENT_WAIT = 3_000

# ─── Quran metadata ──────────────────────────────────────────────────────────


# Ayah count per surah (index 0 = surah 1)
def _load_quran_meta(path: str = "./resources/cdn/static/quran.json") -> list[int]:
    """Read numberOfAyat for each surah from quran.json, ordered by surah number."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    surahs = data["quran"]
    return [surahs[str(i)]["numberOfAyat"] for i in range(1, len(surahs) + 1)]


AYAH_COUNTS = _load_quran_meta()

# Cumulative ayah offset before each surah (surah 1 starts at absolute 1)
_CUMULATIVE = [0]
for _c in AYAH_COUNTS:
    _CUMULATIVE.append(_CUMULATIVE[-1] + _c)


def absolute_ayah(surah: int, ayah: int) -> int:
    """Return the 1-based absolute ayah number in the whole Quran."""
    return _CUMULATIVE[surah - 1] + ayah


def page_num_from_url(image_url: str) -> int:
    """Extract page number from image URL, e.g. .../imgs/042.png → 42."""
    stem = Path(image_url).stem  # e.g. "042"
    try:
        return int(stem)
    except ValueError:
        return 0


# ─── Helpers ─────────────────────────────────────────────────────────────────

VBTN_RE = re.compile(r"^v(\d+)_(\d+)(?:_(\d+))?$")


def parse_vbtn_id(vbtn_id: str):
    """
    Parse vBtn id like  v1_1_1 / v1_2 / v114_3_2
    Returns (surah_num, ayah_num, bbox_num) – all ints; bbox_num defaults to 1.
    """
    m = VBTN_RE.match(vbtn_id)
    if not m:
        return None
    surah = int(m.group(1))
    ayah = int(m.group(2))
    bbox = int(m.group(3)) if m.group(3) else 1
    return surah, ayah, bbox


def parse_style_px(style: str, prop: str) -> float | None:
    """Extract a numeric pixel value from an inline style string."""
    pat = re.compile(rf"{prop}\s*:\s*(-?[\d.]+)px")
    m = pat.search(style)
    return float(m.group(1)) if m else None


def img_full_url(src: str) -> str:
    """Turn a relative ../../ path into an absolute URL."""
    # src looks like  ../../book/Tajweed/epub/EPUB/imgs/001.png
    clean = re.sub(r"^\.\./", "", src.lstrip("./").lstrip(".").lstrip("/"))
    # After stripping leading ../ pairs the path starts with book/…
    # Remove leading slashes just in case
    path = re.sub(r"^\.*/?", "", src)
    # Simplest: just drop the ../../ prefix
    path = re.sub(r"^(\.\.\/)+", "", src)
    return IMG_PREFIX + path


# ─── Core scraping logic ──────────────────────────────────────────────────────


async def scrape_page(page, chapter_number: int):
    """
    Navigate to one chapter page and extract all vBtn bboxes + image URLs.
    Returns a list of dicts:
        {surah, ayah, bbox_index, spread, image_url, top, left, width, height}

    Also returns a list of CSV rows (one per spread that has an image):
        {surah, image_url}
    """
    url = BASE_URL.format(number=chapter_number)
    bbox_records = []
    csv_rows = []

    try:
        await page.goto(url, timeout=PAGE_TIMEOUT)
        # Extra settle time for JS-rendered content
        await page.wait_for_timeout(CONTENT_WAIT)
    except Exception as exc:
        print(f"  [WARN] Chapter {chapter_number}: navigation error – {exc}")
        return bbox_records, csv_rows

    for spread_id in SPREAD_IDS:
        try:
            spread = page.locator(f"#{spread_id}")
            if await spread.count() == 0:
                continue

            # ── Image URL ────────────────────────────────────────────────────
            img_el = spread.locator("img").first
            img_src = ""
            if await img_el.count() > 0:
                img_src = await img_el.get_attribute("src") or ""
                if img_src:
                    img_src = img_full_url(img_src)

            # ── vBtn divs ────────────────────────────────────────────────────
            vbtns = spread.locator("div.vBtn")
            count = await vbtns.count()

            spread_surah = None  # inferred from first valid vBtn on this spread

            for i in range(count):
                btn = vbtns.nth(i)
                btn_id = await btn.get_attribute("id") or ""
                btn_style = await btn.get_attribute("style") or ""

                parsed = parse_vbtn_id(btn_id)
                if not parsed:
                    continue
                surah, ayah, bbox_idx = parsed

                if spread_surah is None:
                    spread_surah = surah

                top = parse_style_px(btn_style, "top")
                left = parse_style_px(btn_style, "left")
                width = parse_style_px(btn_style, "width")
                height = parse_style_px(btn_style, "height")

                bbox_records.append(
                    {
                        "surah": surah,
                        "ayah": ayah,
                        "bbox_index": bbox_idx,
                        "spread": spread_id,
                        "image_url": img_src,
                        "top": top,
                        "left": left,
                        "width": width,
                        "height": height,
                    }
                )

            # One CSV row per spread (surah inferred from vBtns, or chapter_number fallback)
            if img_src:
                csv_rows.append(
                    {
                        "surah": spread_surah
                        if spread_surah is not None
                        else chapter_number,
                        "image_url": img_src,
                    }
                )

        except Exception as exc:
            print(f"  [WARN] Chapter {chapter_number} / #{spread_id}: {exc}")

    return bbox_records, csv_rows


# ─── Build output structures ──────────────────────────────────────────────────


def build_json(all_records: list[dict]) -> dict:
    """
    Build nested JSON:
    {
      "surahs": {
        "1": {
          "ayat": {
            "1": {
              "absolute_number": 1,
              "page_num": 1,
              "bboxes": [
                {"top": 181, "left": 122, "bottom": 230, "right": 340},
                ...
              ]
            }
          }
        }
      }
    }
    """
    surahs: dict = {}

    for r in all_records:
        s_key = str(r["surah"])
        a_key = str(r["ayah"])

        if s_key not in surahs:
            surahs[s_key] = {"ayat": {}}

        ayat = surahs[s_key]["ayat"]
        if a_key not in ayat:
            ayat[a_key] = {
                "absolute_number": absolute_ayah(r["surah"], r["ayah"]),
                "page_num": page_num_from_url(r["image_url"]),
                "bboxes": [],
            }

        top = r["top"] or 0
        left = r["left"] or 0
        width = r["width"] or 0
        height = r["height"] or 0

        ayat[a_key]["bboxes"].append(
            {
                "top": top,
                "left": left,
                "bottom": top + height,
                "right": left + width,
            }
        )

    # Sort bboxes top-to-bottom, left-to-right within each ayah
    for s_data in surahs.values():
        for a_data in s_data["ayat"].values():
            a_data["bboxes"].sort(key=lambda b: (b["top"], b["left"]))

    return {"surahs": surahs}


def write_csv(csv_rows: list[dict], path: Path):
    """One row per page spread: surah number + image URL."""
    fieldnames = ["surah", "image_url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)


def write_json(data: dict, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_bbox_records: list[dict] = []
    all_csv_rows: list[dict] = []

    # Allow limiting chapters via CLI for testing: python scrape.py 1 5
    chapters = CHAPTERS
    if len(sys.argv) >= 3:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        chapters = [c for c in CHAPTERS if start <= c <= end]
        print(f"[INFO] Running subset: chapters {start}–{end} ({len(chapters)} pages)")
    else:
        print(f"[INFO] Scraping {len(chapters)} pages …")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        with tqdm(chapters, unit="page", desc="Scraping") as pbar:
            for chapter in pbar:
                pbar.set_postfix(chapter=chapter)
                bbox_records, csv_rows = await scrape_page(page, chapter)
                all_bbox_records.extend(bbox_records)
                all_csv_rows.extend(csv_rows)
                pbar.set_postfix(chapter=chapter, bboxes=len(all_bbox_records))

                # Small politeness delay
                await asyncio.sleep(0.5)

        await browser.close()

    print(f"\n[INFO] Total bboxes: {len(all_bbox_records)}")

    # Sort bbox records: surah → ayah → bbox_index
    all_bbox_records.sort(key=lambda r: (r["surah"], r["ayah"], r["bbox_index"]))

    # Write CSV (surah + image_url only, sorted by surah)
    all_csv_rows.sort(key=lambda r: r["surah"])
    write_csv(all_csv_rows, CSV_FILE)
    print(f"[OK]  CSV  → {CSV_FILE}  ({len(all_csv_rows)} rows)")

    data = build_json(all_bbox_records)
    write_json(data, JSON_FILE)
    print(f"[OK]  JSON → {JSON_FILE}")

    # Quick summary
    surah_count = len(data["surahs"])
    ayah_count = sum(len(s["ayat"]) for s in data["surahs"].values())
    print(
        f"\nSummary: {surah_count} surahs | {ayah_count} ayat | {len(all_bbox_records)} bboxes"
    )


if __name__ == "__main__":
    asyncio.run(main())
