import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("filters")

def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    tried_formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]

    for fmt in tried_formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Unrecognized date format: %s", value)
        return None

def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)

def apply_filters(
    reviews: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if not filters:
        return reviews

    min_rating = filters.get("minRating")
    max_rating = filters.get("maxRating")
    languages = [l.lower() for l in filters.get("languages", []) if l]
    countries = [c.upper() for c in filters.get("countries", []) if c]
    include_keywords = filters.get("keywordsInclude") or []
    exclude_keywords = filters.get("keywordsExclude") or []
    verified_only = bool(filters.get("verifiedOnly", False))
    date_from = _parse_date(filters.get("dateFrom"))
    date_to = _parse_date(filters.get("dateTo"))

    filtered: List[Dict[str, Any]] = []

    for review in reviews:
        rating = review.get("ratingValue")
        if rating is not None:
            try:
                rating_int = int(rating)
            except (ValueError, TypeError):
                rating_int = None
        else:
            rating_int = None

        if min_rating is not None and rating_int is not None and rating_int < min_rating:
            continue
        if max_rating is not None and rating_int is not None and rating_int > max_rating:
            continue

        if languages:
            lang = (review.get("reviewLanguage") or "").lower()
            if lang and lang not in languages:
                continue

        if countries:
            country = (review.get("consumerCountryCode") or "").upper()
            if country and country not in countries:
                continue

        if verified_only:
            verification = str(review.get("verificationLevel") or "").lower()
            if not verification or verification in {"unverified", "none"}:
                continue

        text_content = (
            (review.get("reviewHeadline") or "")
            + " "
            + (review.get("reviewBody") or "")
        ).strip()

        if include_keywords:
            if not text_content or not _contains_any(text_content, include_keywords):
                continue

        if exclude_keywords and text_content:
            if _contains_any(text_content, exclude_keywords):
                continue

        if date_from or date_to:
            raw_date = review.get("experienceDate") or review.get("datePublished")
            parsed_date = _parse_date(raw_date)
            if parsed_date:
                if date_from and parsed_date < date_from:
                    continue
                if date_to and parsed_date > date_to:
                    continue

        filtered.append(review)

    logger.debug(
        "Filtering complete. Input size: %d, Output size: %d",
        len(reviews),
        len(filtered),
    )
    return filtered