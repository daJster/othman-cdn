import json
from collections import defaultdict

def reverse_quran_map(input_path, output_path):
    """
    Transforms Quran structure from:
        surahs -> ayat -> metadata

    Into:
        pages -> ayat -> metadata (including surah reference)

    Args:
        input_path (str): Path to input JSON file

    Returns:
        dict: Transformed structure grouped by pages
    """

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = defaultdict(lambda: {"ayat": {}})

    surahs = data.get("surahs", {})

    for surah_id, surah_data in surahs.items():
        ayat = surah_data.get("ayat", {})

        for ayah_id, ayah_data in ayat.items():
            page = ayah_data.get("page_num")

            if page is None:
                continue  # skip malformed entries

            pages[str(page)]["ayat"][ayah_id] = {
                "absolute_number": ayah_data.get("absolute_number"),
                "bboxes": ayah_data.get("bboxes", []),
                "surah": int(surah_id)
            }

    result = dict(pages)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    reverse_quran_map('./dist/book_MedinaOld_bbox_norm.json', './dist/book_MedinaOld_bbox_reversed_norm.json')
    reverse_quran_map('./dist/book_Tajweed_bbox_norm.json', './dist/book_Tajweed_bbox_reversed_norm.json')
    reverse_quran_map('./dist/book_Warsh1_bbox_norm.json', './dist/book_Warsh1_bbox_reversed_norm.json')