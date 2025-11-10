import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

import xml.etree.ElementTree as ET

try:
    import pandas as pd  # type: ignore[import]
except Exception:  # noqa: BLE001
    pd = None  # type: ignore[assignment]

logger = logging.getLogger("exporters")

def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

def export_json(reviews: List[Dict[str, Any]], output_dir: Path) -> Path:
    _ensure_dir(output_dir)
    out_path = output_dir / "trustpilot_reviews.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)
    logger.info("Exported JSON: %s", out_path)
    return out_path

def export_csv(reviews: List[Dict[str, Any]], output_dir: Path) -> Path:
    _ensure_dir(output_dir)
    out_path = output_dir / "trustpilot_reviews.csv"

    fieldnames: List[str] = []
    for r in reviews:
        for key in r.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reviews:
            writer.writerow({k: ("" if v is None else v) for k, v in r.items()})

    logger.info("Exported CSV: %s", out_path)
    return out_path

def export_excel(reviews: List[Dict[str, Any]], output_dir: Path) -> Path:
    if pd is None:
        logger.warning(
            "pandas is not installed; skipping Excel export. "
            "Install pandas and openpyxl to enable this feature."
        )
        return output_dir / "trustpilot_reviews.xlsx"

    _ensure_dir(output_dir)
    out_path = output_dir / "trustpilot_reviews.xlsx"
    df = pd.DataFrame(reviews)
    df.to_excel(out_path, index=False)
    logger.info("Exported Excel: %s", out_path)
    return out_path

def export_xml(reviews: List[Dict[str, Any]], output_dir: Path) -> Path:
    _ensure_dir(output_dir)
    out_path = output_dir / "trustpilot_reviews.xml"

    root = ET.Element("reviews")
    for review in reviews:
        review_el = ET.SubElement(root, "review")
        for key, value in review.items():
            child = ET.SubElement(review_el, key)
            child.text = "" if value is None else str(value)

    tree = ET.ElementTree(root)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    logger.info("Exported XML: %s", out_path)
    return out_path

def export_all(
    reviews: List[Dict[str, Any]],
    output_dir: Path,
    formats: Iterable[str],
) -> None:
    output_dir = _ensure_dir(output_dir)
    selected = {fmt.lower() for fmt in formats}

    if "json" in selected:
        export_json(reviews, output_dir)
    if "csv" in selected:
        export_csv(reviews, output_dir)
    if "excel" in selected or "xlsx" in selected:
        export_excel(reviews, output_dir)
    if "xml" in selected:
        export_xml(reviews, output_dir)