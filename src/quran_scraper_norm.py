"""
QuranFlash EDITIONS Bbox Normalizer
===================================
Reads an existing quran bbox JSON (structure: surahs → ayat → bboxes with
pixel top/left/bottom/right) and writes a new JSON whose bbox values are
normalized to size-independent units — fractions of the edition's configured
page size — so positions are decoupled from the image pixel size / aspect
ratio. Only bbox values change; the rest of the document is preserved.

Normalization (inverse of the render math in src/AyahOverlay.tsx, with the
page scale/offset taken from createQuranPageScaleConfig for the edition):

    size   = config.size                      (width / height)
    oX     = offsetX / size.width
    oY     = offsetY / size.height
    left'  =  left  * scaleX / size.width  + oX
    top'   =  top   * scaleY / size.height + oY
    right' =  right * scaleX / size.width  + oX
    bottom'= bottom * scaleY / size.height + oY

Per-ayah page key comes from the ayah's "page_num"; missing keys fall back
to the edition's "default" page scale.

Usage:
    python quran_scraper_2.py INPUT_JSON OUTPUT_JSON [--edition=SLUG]

Edition default: Tajweed. Available: Tajweed, MedinaOld, Warsh1.
"""

import argparse
import copy
import json
import sys

# ─── Scale config (mirrors createQuranPageScaleConfig in src/data/configData.ts) ─

PAGE_SCALE_CONFIG = {
    "Tajweed": {
        "size": {"height": 600, "width": 412},
        "pages": {
            "1": {"scaleX": 0.9, "scaleY": 0.88, "offsetX": -5, "offsetY": -20},
            "2": {"scaleX": 0.9, "scaleY": 0.88, "offsetX": -5, "offsetY": -20},
            "default": {"scaleX": 0.85, "scaleY": 0.897, "offsetX": -5, "offsetY": 0},
        },
    },
    "MedinaOld": {
        "size": {"height": 600, "width": 412},
        "pages": {
            "4": {"scaleX": 0.95, "scaleY": 0.92, "offsetX": -10, "offsetY": -8},
            "5": {"scaleX": 0.95, "scaleY": 0.92, "offsetX": -18, "offsetY": -8},
            "default": {"scaleX": 0.93, "scaleY": 0.9, "offsetX": -8, "offsetY": -2},
        },
    },
    "Warsh1": {
        "size": {"height": 600, "width": 412},
        "pages": {
            "4": {"scaleX": 0.9, "scaleY": 0.85, "offsetX": -3, "offsetY": 16},
            "5": {"scaleX": 0.83, "scaleY": 0.858, "offsetX": 10, "offsetY": 16},
            "default": {"scaleX": 0.865, "scaleY": 0.89, "offsetX": -2, "offsetY": 2},
        },
    },
}

DEFAULT_EDITION = "Tajweed"


# ─── Normalization ────────────────────────────────────────────────────────────


def normalize_bbox(bbox: dict, page_num: int, edition_slug: str) -> dict:
    """
    Map a pixel bbox {top, left, bottom, right} into normalized units:
    fractions of the edition's configured page size, with the page's scale
    applied and the (normalized) offset added back.
    """
    cfg = PAGE_SCALE_CONFIG[edition_slug]
    page_key = str(page_num)
    scale = cfg["pages"].get(page_key) or cfg["pages"]["default"]

    size_w = cfg["size"]["width"]
    size_h = cfg["size"]["height"]

    s_x = scale["scaleX"]
    s_y = scale["scaleY"]
    o_x = scale["offsetX"] / size_w
    o_y = scale["offsetY"] / size_h

    top = round((bbox.get("top") or 0) * s_y / size_h + o_y, 3)
    left = round((bbox.get("left") or 0) * s_x / size_w + o_x, 3)
    bottom = round((bbox.get("bottom") or 0) * s_y / size_h + o_y, 3)
    right = round((bbox.get("right") or 0) * s_x / size_w + o_x, 3)

    return {
        **bbox,
        "top": top,
        "left": left,
        "bottom": bottom,
        "right": right,
    }


def normalize_json(data: dict, edition_slug: str) -> dict:
    """
    Deep-copy the input document and rewrite every bbox value in normalized
    units. Non-bbox fields (absolute_number, page_num, …) are left untouched.
    """
    result = copy.deepcopy(data)
    surahs = result.get("surahs")
    if not isinstance(surahs, dict):
        sys.exit(f"[ERROR] JSON missing 'surahs' object: {type(surahs).__name__}")

    for s_data in surahs.values():
        ayat = s_data.get("ayat", {})
        if not isinstance(ayat, dict):
            continue
        for a_data in ayat.values():
            page_num = int(a_data.get("page_num", 0) or 0)
            bboxes = a_data.get("bboxes")
            if not isinstance(bboxes, list):
                continue
            a_data["bboxes"] = [
                normalize_bbox(b, page_num, edition_slug) for b in bboxes
            ]

    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Normalize quran bbox pixel values to size-independent units.",
    )
    parser.add_argument("input_json", help="Path to the existing (pixel) bbox JSON")
    parser.add_argument("output_json", help="Path to write the normalized JSON")
    parser.add_argument(
        "--edition",
        default=DEFAULT_EDITION,
        help=f"Edition scale config to use (default: {DEFAULT_EDITION})",
    )
    args = parser.parse_args()

    edition = args.edition
    if edition not in PAGE_SCALE_CONFIG:
        available = ", ".join(PAGE_SCALE_CONFIG)
        sys.exit(f"[ERROR] Unknown edition '{edition}'. Available: {available}")

    with open(args.input_json, encoding="utf-8") as f:
        data = json.load(f)

    result = normalize_json(data, edition)

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size = PAGE_SCALE_CONFIG[edition]["size"]
    bbox_count = sum(
        len(b["bboxes"])
        for s in result["surahs"].values()
        for b in s.get("ayat", {}).values()
    )
    print(
        f"[OK]  {args.input_json} -> {args.output_json}  "
        f"({bbox_count} bboxes normalized to "
        f"{size['width']}x{size['height']}, edition '{edition}')"
    )


if __name__ == "__main__":
    main()