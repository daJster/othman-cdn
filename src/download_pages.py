"""
QuranFlash Page Downloader
===========================
Reads book_{Type}.csv and downloads every unique image_url
into /book/{Type}/pages/*.png

Usage:
    python download_pages.py book_Tajweed.csv
"""

import csv
import sys
import httpx
from pathlib import Path
from urllib.parse import urlparse
from tqdm import tqdm

# ─── Config ───────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://app.quranflash.com/",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def infer_type(csv_path: Path) -> str:
    """Extract Type from filename: book_EDITION.csv → EDITION"""
    stem = csv_path.stem          # book_Tajweed
    parts = stem.split("_", 1)
    return parts[1] if len(parts) == 2 else stem

def load_urls(csv_path: Path) -> list[str]:
    """Return deduplicated list of image_url values from the CSV, preserving order."""
    seen = set()
    urls = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("image_url", "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls

def url_to_filename(url: str) -> str:
    """Use the last path segment as the local filename (e.g. 001.png)."""
    return Path(urlparse(url).path).name

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python download_pages.py book_EDITION.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"[ERROR] File not found: {csv_path}")
        sys.exit(1)

    book_type  = infer_type(csv_path)
    output_dir = Path("dist/cdn/public") / book_type / "pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    urls = load_urls(csv_path)
    print(f"[INFO] {len(urls)} unique pages to download → {output_dir}")

    ok = skipped = failed = 0

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for url in tqdm(urls, unit="img", desc="Downloading"):
            filename = url_to_filename(url)
            dest = output_dir / filename

            if dest.exists():
                skipped += 1
                continue

            try:
                r = client.get(url)
                r.raise_for_status()
                dest.write_bytes(r.content)
                ok += 1
            except Exception as exc:
                tqdm.write(f"  [WARN] {url} – {exc}")
                failed += 1

    print(f"\nDone: {ok} downloaded | {skipped} skipped | {failed} failed")
    print(f"Pages saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()