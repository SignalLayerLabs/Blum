"""Public adapters; current state, discovery and historical vintages stay distinct."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
import json
import math
import re
from typing import Protocol
from urllib.parse import quote, urlencode
import xml.etree.ElementTree as ET

import feedparser
from sqlalchemy import select

from app.ingestion.news_ingestor import clean_text, parse_entry_time
from app.models import Asset, NewsArticle, NewsAssetLink, SentimentAnalysis
from app.services.market_clock import utc_naive
from .contracts import EvidenceLink, ProviderResult, SourceEvidence
from .fetch import PublicEvidenceFetcher


class InformationProvider(Protocol):
    provider: str

    def fetch(
        self, *, cursor: dict, as_of: datetime, deadline: float
    ) -> ProviderResult: ...


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return utc_naive(value)
    try:
        return utc_naive(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _page(
    provider, records, cursor, observed_at, *, metadata=None, capability="events"
):
    limit = max(1, min(200, int(cursor.get("_limit", 50))))
    selected, pending = records[:limit], records[limit:]
    evidence, links = [], []
    for row in selected:
        item = SourceEvidence.create(
            provider=provider,
            canonical_url=row["url"],
            payload=row["payload"],
            language=row.get("language", "und"),
            published_at=parse_time(row.get("published_at")),
            observed_at=parse_time(row["observed_at"]),
            available_at=parse_time(row["available_at"]),
            historical_availability_verified=row.get("verified", False),
            extraction_version="information-v1",
        )
        evidence.append(item)
        for key, kind, confidence, reason in row.get("links", []):
            links.append(
                EvidenceLink(
                    item.evidence_id, key, kind, confidence, reason, "provider-v1"
                )
            )
    saved = {
        "pending": pending,
        "etag": (metadata or {}).get("etag", cursor.get("etag")),
    }
    return ProviderResult(
        provider,
        "AVAILABLE" if evidence else "EMPTY",
        tuple(evidence),
        observed_at=observed_at,
        links=tuple(links),
        cursor=json.dumps(saved, ensure_ascii=False, allow_nan=False),
        source_at=max(
            (e.published_at for e in evidence if e.published_at), default=None
        ),
        coverage={
            "capability": capability,
            "accepted": len(evidence),
            "pending": len(pending),
        },
    )


class _RemoteProvider:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or PublicEvidenceFetcher()

    def _pending(self, cursor, as_of):
        if cursor.get("pending"):
            return _page(self.provider, cursor["pending"], cursor, as_of)
        return None

    def _response(self, url, cursor, deadline):
        response = self.fetcher.fetch(url, deadline=deadline, etag=cursor.get("etag"))
        if response.status == "AVAILABLE":
            return response, None
        status = "EMPTY" if response.status == "NOT_MODIFIED" else response.status
        if status not in {
            "EMPTY",
            "UNAVAILABLE",
            "QUOTA_LIMITED",
            "ENTITLEMENT_REQUIRED",
        }:
            status = "UNAVAILABLE"
        return response, ProviderResult(
            self.provider,
            status,
            (),
            observed_at=response.observed_at,
            retry_at=response.retry_at,
            error_code=response.error_code,
            cursor=json.dumps(
                {k: v for k, v in cursor.items() if not k.startswith("_")}
            ),
        )

    def _invalid(self, response, code):
        return ProviderResult(
            self.provider,
            "UNAVAILABLE",
            (),
            observed_at=response.observed_at,
            error_code=code,
        )


class CentralBankProvider(_RemoteProvider):
    URLS = {
        "fed": "https://www.federalreserve.gov/feeds/press_all.xml",
        "ecb": "https://www.ecb.europa.eu/rss/press.html",
    }

    def __init__(self, bank, *, fetcher=None):
        super().__init__(fetcher)
        if bank not in self.URLS:
            raise ValueError("Unsupported central bank")
        self.bank, self.provider = bank, bank + ":press"

    def fetch(self, *, cursor, as_of, deadline):
        pending = self._pending(cursor, as_of)
        if pending is not None:
            return pending
        response, failure = self._response(self.URLS[self.bank], cursor, deadline)
        if failure:
            return failure
        try:
            if (
                b"<!doctype" in response.body.lower()
                or b"<!entity" in response.body.lower()
            ):
                raise ValueError()
            root = ET.fromstring(response.body)
            if root.tag.rsplit("}", 1)[-1] not in {"rss", "feed", "RDF"}:
                raise ValueError()
            parsed = feedparser.parse(response.body)
            if len(parsed.entries) > 500:
                return self._invalid(response, "EXTRACTION_BUDGET_EXCEEDED")
        except (ET.ParseError, ValueError):
            return self._invalid(response, "BAD_XML")
        observed = response.observed_at.isoformat()
        records = []
        for entry in parsed.entries:
            if not entry.get("link") or not entry.get("title"):
                continue
            published = parse_entry_time(entry)
            records.append(
                {
                    "url": entry.link,
                    "published_at": published.isoformat() if published else None,
                    "observed_at": observed,
                    "available_at": observed,
                    "language": entry.get(
                        "language", parsed.feed.get("language", "und")
                    ),
                    "payload": {
                        "title": clean_text(entry.title, 500),
                        "text": clean_text(entry.get("summary", ""), 4000),
                        "source_capability": "central_bank_release",
                        "bank": self.bank,
                    },
                    "links": [
                        [
                            "USD" if self.bank == "fed" else "EUR",
                            "currency",
                            1.0,
                            "official central-bank release",
                        ]
                    ],
                }
            )
        return _page(
            self.provider,
            records,
            cursor,
            response.observed_at,
            metadata=response.headers,
        )


class FredVintageProvider(_RemoteProvider):
    def __init__(self, series_id, *, vintage_date=None, api_key="", fetcher=None):
        super().__init__(fetcher)
        from app.services.macro import FRED_SERIES

        if series_id not in FRED_SERIES:
            raise ValueError("Unsupported configured FRED series")
        self.series, self.meta = series_id, FRED_SERIES[series_id]
        self.vintage_date = (
            datetime.fromisoformat(vintage_date).date() if vintage_date else None
        )
        self.api_key = api_key
        self.provider = f"fred:{'vintage' if vintage_date else 'current'}:{series_id}"

    def fetch(self, *, cursor, as_of, deadline):
        if self.vintage_date and not self.api_key:
            return ProviderResult(
                self.provider,
                "ENTITLEMENT_REQUIRED",
                (),
                observed_at=as_of,
                error_code="FRED_API_KEY_REQUIRED",
            )
        if self.vintage_date and self.vintage_date >= as_of.date():
            return ProviderResult(
                self.provider,
                "UNAVAILABLE",
                (),
                observed_at=as_of,
                error_code="VINTAGE_NOT_YET_COMPLETE",
            )
        if self.vintage_date:
            params = {
                "series_id": self.series,
                "file_type": "json",
                "api_key": self.api_key,
                "realtime_start": str(self.vintage_date),
                "realtime_end": str(self.vintage_date),
                "observation_end": str(self.vintage_date),
                "sort_order": "desc",
                "limit": 10,
            }
            url = "https://api.stlouisfed.org/fred/series/observations?" + urlencode(
                params
            )
        else:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(
                {"id": self.series}
            )
        response, failure = self._response(url, cursor, deadline)
        if failure:
            return failure
        try:
            if self.vintage_date:
                rows = json.loads(response.body)["observations"]
                candidates = [
                    (row["date"], row["value"])
                    for row in rows
                    if row.get("realtime_start") == str(self.vintage_date)
                    and row.get("realtime_end") == str(self.vintage_date)
                ]
            else:
                reader = csv.DictReader(StringIO(response.body.decode("utf-8-sig")))
                if not {"observation_date", self.series}.issubset(
                    reader.fieldnames or ()
                ):
                    raise ValueError()
                candidates = [
                    (row["observation_date"], row[self.series]) for row in reader
                ]
            valid = []
            for period, value in candidates:
                if value in {".", "", None}:
                    continue
                number = float(value)
                date = datetime.fromisoformat(period).date()
                if math.isfinite(number) and date <= (
                    self.vintage_date or as_of.date()
                ):
                    valid.append((date, number))
        except (ValueError, KeyError, TypeError, UnicodeError):
            return self._invalid(response, "BAD_MACRO_DATA")
        if not valid:
            return _page(
                self.provider,
                [],
                cursor,
                response.observed_at,
                metadata=response.headers,
            )
        period, number = max(valid)
        payload = {
            "series_id": self.series,
            "period": str(period),
            "value": number,
            "unit": self.meta["unit"],
            "title": self.meta["label"],
            "source_capability": (
                "vintage_state" if self.vintage_date else "current_state"
            ),
        }
        available = response.observed_at
        if self.vintage_date:
            # The API supplies a date, not an intraday publication instant.
            available = datetime.combine(
                self.vintage_date + timedelta(days=1), datetime.min.time()
            )
            payload["historical_vintage"] = {
                "realtime_start": str(self.vintage_date),
                "realtime_end": str(self.vintage_date),
                "reference": "https://fred.stlouisfed.org/docs/api/fred/realtime_period.html",
            }
        row = {
            "url": f"https://fred.stlouisfed.org/series/{self.series}?"
            + urlencode({"observation_date": str(period)}),
            "payload": payload,
            "published_at": None,
            "observed_at": response.observed_at.isoformat(),
            "available_at": available.isoformat(),
            "verified": bool(self.vintage_date),
            "language": "en",
            "links": [["USD", "currency", 1.0, "US macro series"]],
        }
        return _page(
            self.provider,
            [row],
            cursor,
            response.observed_at,
            metadata=response.headers,
            capability=payload["source_capability"],
        )


class SecFilingsProvider(_RemoteProvider):
    def __init__(self, cik, ticker, *, fetcher=None):
        super().__init__(fetcher)
        if not re.fullmatch(r"\d{1,10}", str(cik)):
            raise ValueError("Invalid CIK")
        self.cik, self.ticker = str(cik).zfill(10), ticker.upper()
        self.provider = "sec:" + self.cik

    def fetch(self, *, cursor, as_of, deadline):
        pending = self._pending(cursor, as_of)
        if pending is not None:
            return pending
        response, failure = self._response(
            f"https://data.sec.gov/submissions/CIK{self.cik}.json", cursor, deadline
        )
        if failure:
            return failure
        try:
            payload = json.loads(response.body)
            recent = payload["filings"]["recent"]
            records = []
            for i, accession in enumerate(recent["accessionNumber"]):
                form, document = recent["form"][i], recent["primaryDocument"][i]
                if form not in {
                    "8-K",
                    "10-K",
                    "10-Q",
                    "6-K",
                    "20-F",
                    "8-K/A",
                    "10-K/A",
                    "10-Q/A",
                }:
                    continue
                if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                    raise ValueError()
                published = parse_time(
                    (
                        recent.get("acceptanceDateTime")
                        or [None] * len(recent["accessionNumber"])
                    )[i]
                )
                records.append(
                    {
                        "url": f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/{accession.replace('-', '')}/{quote(document, safe='')}",
                        "published_at": published.isoformat() if published else None,
                        "observed_at": response.observed_at.isoformat(),
                        "available_at": response.observed_at.isoformat(),
                        "language": "en",
                        "payload": {
                            "source_capability": "issuer_filing",
                            "form": form,
                            "accession": accession,
                            "title": f"{payload.get('name', self.ticker)} {form}",
                            "cik": self.cik,
                        },
                        "links": [[self.ticker, "issuer", 1.0, "exact SEC CIK issuer"]],
                    }
                )
        except (ValueError, KeyError, TypeError, IndexError):
            return self._invalid(response, "BAD_SEC_DATA")
        if len(records) > 500:
            return self._invalid(response, "EXTRACTION_BUDGET_EXCEEDED")
        return _page(
            self.provider,
            records,
            cursor,
            response.observed_at,
            metadata=response.headers,
        )


class GdeltDiscoveryProvider(_RemoteProvider):
    provider = "gdelt:global"

    def fetch(self, *, cursor, as_of, deadline):
        pending = self._pending(cursor, as_of)
        if pending is not None:
            return pending
        url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
            {
                "query": '("Federal Reserve" OR "European Central Bank" OR earnings)',
                "mode": "artlist",
                "format": "json",
                "timespan": "24h",
                "maxrecords": 100,
                "sort": "datedesc",
            }
        )
        response, failure = self._response(url, cursor, deadline)
        if failure:
            return failure
        try:
            articles = json.loads(response.body)["articles"]
            records = [
                {
                    "url": row["url"],
                    "published_at": None,
                    "observed_at": response.observed_at.isoformat(),
                    "available_at": response.observed_at.isoformat(),
                    "language": row.get("language", "und"),
                    "payload": {
                        "source_capability": "discovery",
                        "title": clean_text(row.get("title", ""), 500),
                        "index_seen_at": row.get("seendate"),
                        "publisher_domain": row.get("domain"),
                    },
                }
                for row in articles
            ]
        except (ValueError, TypeError, KeyError):
            return self._invalid(response, "BAD_DISCOVERY_DATA")
        return _page(
            self.provider,
            records,
            cursor,
            response.observed_at,
            metadata=response.headers,
            capability="discovery",
        )


class ExistingNewsProvider:
    provider = "news:stored"

    def __init__(self, db):
        self.db = db

    def fetch(self, *, cursor, as_of, deadline):
        limit = max(1, min(200, int(cursor.get("_limit", 50))))
        rows = self.db.scalars(
            select(NewsArticle)
            .where(
                NewsArticle.id > int(cursor.get("last_id", 0)),
                NewsArticle.created_at <= as_of,
            )
            .order_by(NewsArticle.id)
            .limit(limit)
        ).all()
        items, links, invalid = [], [], 0
        for article in rows:
            analysis = self.db.scalar(
                select(SentimentAnalysis)
                .where(
                    SentimentAnalysis.article_id == article.id,
                    SentimentAnalysis.created_at <= as_of,
                )
                .order_by(
                    SentimentAnalysis.created_at.desc(), SentimentAnalysis.id.desc()
                )
                .limit(1)
            )
            sentiment = (
                {
                    "sentiment_score": analysis.score,
                    "sentiment_model": analysis.model_name,
                    "sentiment_available_at": analysis.created_at.isoformat(),
                }
                if analysis
                else {}
            )
            try:
                item = SourceEvidence.create(
                    provider=self.provider,
                    canonical_url=article.url,
                    language="und",
                    published_at=article.published_at,
                    observed_at=as_of,
                    available_at=as_of,
                    payload={
                        "title": article.title,
                        "text": article.summary,
                        "publisher": article.source,
                        "source_capability": "news",
                        "legacy_created_at": article.created_at.isoformat(),
                        **sentiment,
                    },
                    extraction_version="legacy-news-v1",
                )
            except ValueError:
                invalid += 1
                continue
            items.append(item)
            for link, asset in self.db.execute(
                select(NewsAssetLink, Asset)
                .join(Asset, Asset.id == NewsAssetLink.asset_id)
                .where(NewsAssetLink.article_id == article.id)
            ):
                links.append(
                    EvidenceLink(
                        item.evidence_id,
                        asset.ticker,
                        "issuer",
                        max(0, min(1, link.relevance_score)),
                        "legacy heuristic asset linkage; not certified exact issuer",
                        "legacy-news-v1",
                    )
                )
        return ProviderResult(
            self.provider,
            "AVAILABLE" if items else "EMPTY",
            tuple(items),
            observed_at=as_of,
            links=tuple(links),
            cursor=json.dumps(
                {"last_id": rows[-1].id if rows else cursor.get("last_id", 0)}
            ),
            coverage={
                "capability": "stored_news",
                "accepted": len(items),
                "invalid": invalid,
            },
        )
