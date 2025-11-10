import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from extractors.trustpilot_parser import TrustpilotScraper
from extractors.utils_filters import apply_filters
from outputs.exporters import export_all

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
DEFAULT_CONFIG_PATH = Path("src/config/settings.example.json")
DEFAULT_OUTPUT_DIR = Path("data")

def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

def load_config(path: Path) -> Dict[str, Any]:
    logger = logging.getLogger("config")
    if not path.exists():
        logger.warning(
            "Config file %s not found, using built-in defaults instead.", path
        )
        return {
            "companyUrl": "https://www.trustpilot.com/review/www.trustpilot.com",
            "maxPages": 1,
            "minDelay": 1.0,
            "maxDelay": 3.0,
            "filters": {
                "minRating": 1,
                "maxRating": 5,
                "languages": [],
                "countries": [],
                "keywordsInclude": [],
                "keywordsExclude": [],
                "verifiedOnly": False,
                "dateFrom": None,
                "dateTo": None,
            },
            "exportFormats": ["json", "csv"],
            "outputDir": "data",
        }

    with path.open("r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse config file %s: %s", path, exc)
            raise SystemExit(1)

    return cfg

def run_scraper(config: Dict[str, Any], output_dir: Optional[Path] = None) -> None:
    logger = logging.getLogger("runner")

    company_url = config.get("companyUrl")
    if not company_url:
        logger.error("Config is missing 'companyUrl'. Aborting.")
        raise SystemExit(1)

    max_pages = int(config.get("maxPages", 1))
    min_delay = float(config.get("minDelay", 1.0))
    max_delay = float(config.get("maxDelay", 3.0))
    filters = config.get("filters") or {}
    export_formats = config.get("exportFormats") or ["json", "csv"]

    if output_dir is None:
        cfg_output_dir = config.get("outputDir")
        if cfg_output_dir:
            output_dir = Path(cfg_output_dir)
        else:
            output_dir = DEFAULT_OUTPUT_DIR

    logger.info(
        "Starting scrape for %s (max_pages=%d, delay=[%.2f, %.2f])",
        company_url,
        max_pages,
        min_delay,
        max_delay,
    )

    scraper = TrustpilotScraper(
        company_url=company_url,
        min_delay=min_delay,
        max_delay=max_delay,
    )

    all_reviews: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        logger.info("Fetching page %d of %d", page, max_pages)
        try:
            html = scraper.fetch_page(page)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch page %d: %s", page, exc)
            break

        page_reviews = scraper.parse_page(html)
        logger.info("Parsed %d reviews from page %d", len(page_reviews), page)

        if not page_reviews:
            logger.info("No more reviews found. Stopping pagination.")
            break

        all_reviews.extend(page_reviews)

    logger.info("Total reviews scraped before filtering: %d", len(all_reviews))
    filtered_reviews = apply_filters(all_reviews, filters)
    logger.info("Total reviews after filtering: %d", len(filtered_reviews))

    if not filtered_reviews:
        logger.warning("No reviews after applying filters. Nothing to export.")
        return

    export_all(filtered_reviews, output_dir=output_dir, formats=export_formats)
    logger.info("Scraping and export completed successfully.")

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trustpilot Reviews Scraper - Bitbash Demo"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to JSON config file (default: src/config/settings.example.json)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        help="Override output directory from config file.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Override maxPages from config file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity level (-v, -vv).",
    )
    return parser.parse_args(argv)

def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    setup_logging(args.verbose)

    config_path = Path(args.config)
    config = load_config(config_path)

    if args.max_pages is not None:
        config["maxPages"] = args.max_pages

    output_dir = Path(args.output_dir) if args.output_dir else None

    try:
        run_scraper(config, output_dir=output_dir)
    except KeyboardInterrupt:
        logging.getLogger("runner").warning("Interrupted by user.")
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("runner").exception("Unexpected error: %s", exc)
        raise SystemExit(1)

if __name__ == "__main__":
    main(sys.argv[1:])