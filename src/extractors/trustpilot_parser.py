import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("trustpilot")

@dataclass
class TrustpilotScraper:
    company_url: str
    min_delay: float = 1.0
    max_delay: float = 3.0
    timeout: int = 20
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _build_page_url(self, page: int) -> str:
        if page <= 1:
            return self.company_url

        parsed = urlparse(self.company_url)
        query = dict(parse_qsl(parsed.query))
        query["page"] = str(page)
        new_query = urlencode(query)
        new_parsed = parsed._replace(query=new_query)
        url = urlunparse(new_parsed)
        logger.debug("Built page URL %s for page %d", url, page)
        return url

    def fetch_page(self, page: int) -> str:
        url = self._build_page_url(page)
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.debug("Sleeping for %.2f seconds before request.", delay)
        time.sleep(delay)

        logger.info("Requesting URL: %s", url)
        resp = self.session.get(url, timeout=self.timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.error("HTTP error on %s: %s", url, exc)
            raise

        logger.debug("Received %d bytes from %s", len(resp.text), url)
        return resp.text

    def parse_page(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        reviews: List[Dict[str, Any]] = []

        reviews.extend(self._parse_from_ld_json(soup))

        if not reviews:
            logger.debug("No reviews from ld+json. Falling back to HTML card parsing.")
            reviews.extend(self._parse_from_cards(soup))

        logger.debug("Parsed %d reviews from page.", len(reviews))
        return reviews

    def _parse_from_ld_json(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        reviews: List[Dict[str, Any]] = []

        for script in scripts:
            raw = script.string or script.get_text(strip=True)
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            extracted = self._extract_reviews_from_ld_block(data)
            reviews.extend(extracted)

        return reviews

    def _extract_reviews_from_ld_block(
        self, data: Union[Dict[str, Any], List[Any]]
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        if isinstance(data, list):
            for item in data:
                results.extend(self._extract_reviews_from_ld_block(item))
            return results

        if not isinstance(data, dict):
            return results

        if data.get("@type") == "Review":
            normalized = self._normalize_ld_review(data)
            if normalized:
                results.append(normalized)

        if "review" in data:
            nested = data["review"]
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict) and item.get("@type") == "Review":
                        normalized = self._normalize_ld_review(item)
                        if normalized:
                            results.append(normalized)
            elif isinstance(nested, dict) and nested.get("@type") == "Review":
                normalized = self._normalize_ld_review(nested)
                if normalized:
                    results.append(normalized)

        return results

    def _normalize_ld_review(self, review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rating_obj = review.get("reviewRating", {})
        author = review.get("author", {})
        if isinstance(author, dict):
            author_name = author.get("name")
        else:
            author_name = author

        review_id = review.get("@id") or review.get("url") or ""
        if review_id:
            review_id = str(review_id).rsplit("/", 1)[-1]

        result: Dict[str, Any] = {
            "reviewId": review_id or None,
            "authorName": author_name or None,
            "datePublished": review.get("datePublished"),
            "reviewHeadline": review.get("headline") or review.get("name"),
            "reviewBody": review.get("reviewBody"),
            "reviewLanguage": review.get("inLanguage"),
            "ratingValue": self._safe_int(rating_obj.get("ratingValue")),
            "verificationLevel": review.get("isVerified") or None,
            "numberOfReviews": self._safe_int(review.get("authorReviewCount")),
            "consumerCountryCode": None,
            "experienceDate": review.get("datePublished"),
            "likes": self._safe_int(review.get("upvoteCount")),
            "replyMessage": None,
            "replyPublishedDate": None,
            "replyUpdatedDate": None,
        }

        response = review.get("publisherResponse") or review.get("reply")
        if isinstance(response, dict):
            result["replyMessage"] = response.get("text") or response.get("description")
            result["replyPublishedDate"] = response.get("datePublished")
            result["replyUpdatedDate"] = response.get("dateModified")

        return result

    def _parse_from_cards(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        reviews: List[Dict[str, Any]] = []

        card_selectors = [
            "[data-review-id]",
            "[data-service-review-card-paper]",
            "article.review",
        ]

        seen_ids = set()

        for selector in card_selectors:
            for card in soup.select(selector):
                review_id = card.get("data-review-id") or card.get("id")
                if review_id and review_id in seen_ids:
                    continue

                author_name = None
                author_el = card.select_one('[data-consumer-name-typography]')
                if not author_el:
                    author_el = card.select_one(".consumer-information__name")
                if author_el:
                    author_name = author_el.get_text(strip=True) or None

                headline_el = card.select_one("[data-review-title-typography]")
                if not headline_el:
                    headline_el = card.select_one("h2")
                review_headline = (
                    headline_el.get_text(strip=True) if headline_el else None
                )

                body_el = card.select_one("[data-review-text-typography]")
                if not body_el:
                    body_el = card.select_one("p")
                review_body = body_el.get_text(strip=True) if body_el else None

                rating = None
                rating_el = card.select_one("[data-service-review-rating] [data-rating]")
                if rating_el:
                    rating = self._safe_int(rating_el.get("data-rating"))
                else:
                    rating_el = card.select_one("meta[itemprop='ratingValue']")
                    if rating_el and rating_el.get("content"):
                        rating = self._safe_int(rating_el.get("content"))

                date_published = None
                date_el = card.select_one("time")
                if date_el and date_el.get("datetime"):
                    date_published = date_el["datetime"]
                elif date_el:
                    date_published = date_el.get_text(strip=True)

                language = card.get("lang") or None

                likes = None
                likes_el = card.select_one("[data-review-useful-count]")
                if likes_el:
                    likes = self._safe_int(likes_el.get_text(strip=True))

                reply_message = None
                reply_published = None
                reply_updated = None
                reply_container = card.select_one("[data-company-reply-container]")
                if reply_container:
                    msg_el = reply_container.select_one("p")
                    if msg_el:
                        reply_message = msg_el.get_text(strip=True)
                    reply_time_el = reply_container.select_one("time")
                    if reply_time_el and reply_time_el.get("datetime"):
                        reply_published = reply_time_el["datetime"]

                country = None
                country_el = card.select_one("[data-consumer-country-flag]")
                if country_el and country_el.get("alt"):
                    alt = country_el["alt"]
                    country = alt.split("(")[-1].rstrip(")") if "(" in alt else alt

                data: Dict[str, Any] = {
                    "reviewId": review_id,
                    "authorName": author_name,
                    "datePublished": date_published,
                    "reviewHeadline": review_headline,
                    "reviewBody": review_body,
                    "reviewLanguage": language,
                    "ratingValue": rating,
                    "verificationLevel": None,
                    "numberOfReviews": None,
                    "consumerCountryCode": country,
                    "experienceDate": None,
                    "likes": likes,
                    "replyMessage": reply_message,
                    "replyPublishedDate": reply_published,
                    "replyUpdatedDate": reply_updated,
                }

                reviews.append(data)
                if review_id:
                    seen_ids.add(review_id)

        return reviews

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_iso(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None