"""
download_export.py
------------------
Downloads the Open Food Facts full CSV export (~9GB compressed).
Streams to disk — does not load into memory.

Usage:
    python pipeline/download_export.py

Output:
    data/raw/off_full_export.csv.gz   (~9GB)

After download, run explore_export.py to check column names
before running the full pipeline.
"""

import requests
import os
from datetime import datetime

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR   = os.path.join(ROOT, "data", "raw")
OUT_PATH  = os.path.join(RAW_DIR, "off_full_export.csv.gz")

URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"

USER_AGENT = "FunctionalFoodRadar/1.0 (student project; github.com/julialenc/functional-foods-radar)"


def download():
    print(f"\nFunctional Food Radar - download_export.py")
    print(f"URL:    {URL}")
    print(f"Output: {OUT_PATH}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(URL, headers=headers, stream=True, timeout=120)
    response.raise_for_status()

    total = int(response.headers.get("content-length", 0))
    total_mb = total / (1024 * 1024)
    downloaded = 0
    chunk_size = 1024 * 1024  # 1MB chunks

    print(f"File size: {total_mb:.0f} MB")
    print(f"Downloading...\n")

    with open(OUT_PATH, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                pct = (downloaded / total * 100) if total else 0
                done_mb = downloaded / (1024 * 1024)
                print(f"\r  {done_mb:.0f} MB / {total_mb:.0f} MB  ({pct:.1f}%)", end="", flush=True)

    print(f"\n\nDone. {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Saved -> {OUT_PATH}")
    size_gb = os.path.getsize(OUT_PATH) / (1024**3)
    print(f"File size on disk: {size_gb:.2f} GB\n")


if __name__ == "__main__":
    download()