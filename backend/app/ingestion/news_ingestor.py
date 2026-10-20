from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import re
import time

import feedparser
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.orchestrator import AIOrchestrator
from app.core.config import get_settings
from app.ingestion.rss_sources import RSS_SOURCES, asset_web_sources, thematic_web_sources
from app.models import Asset, EmbeddingVector, NewsArticle, NewsAssetLink, SentimentAnalysis


HEADERS = {
    "User-Agent": "Blum-AI-Financial-Intelligence/0.3 public research demo"
}

THEME_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "gpu", "data center", "accelerator", "llm"],
    "Rates": ["fed", "rate", "rates", "yield", "treasury", "inflation", "cpi", "pce"],
    "Earnings": ["earnings", "revenue", "profit", "guidance", "margin", "eps"],
    "Geopolitics": ["war", "sanction", "tariff", "china", "russia", "middle east"],
    "M&A": ["merger", "acquisition", "takeover", "deal", "buyout"],
    "Regulation": ["sec", "regulator", "antitrust", "probe", "investigation"],
    "Supply Chain": ["supply chain", "shortage", "inventory", "shipping", "logistics"],
    "Innovation": ["innovation", "robotics", "automation", "cloud", "cyber"],
    "Energy": ["oil", "gas", "opec", "crude", "renewable", "clean energy"],
}

EVENT_KEYWORDS = {
    "earnings": ["earnings", "eps", "revenue", "profit", "margin", "quarter"],
    "guidance": ["guidance", "forecast", "outlook", "raised", "cut forecast", "warns"],
    "m_and_a": ["merger", "acquisition", "takeover", "buyout", "deal"],
    "regulation": ["regulator", "sec", "antitrust", "probe", "investigation", "ban"],
    "analyst_revision": ["upgrade", "downgrade", "price target", "analyst"],
    "product": ["launch", "product", "chip", "platform", "drug", "approval"],
    "supply_chain": ["supply chain", "shortage", "inventory", "shipping"],
    "capital_return": ["buyback", "repurchase", "dividend"],
    "macro": ["fed", "inflation", "rates", "yield", "cpi", "jobs report"],
}


class NewsIngestor:
    def __init__(self, ai: AIOrchestrator | None = None, *, fetcher=None):
        from app.services.information.fetch import PublicEvidenceFetcher
        self.ai = ai or AIOrchestrator()
        self.settings = get_settings()
        self.fetcher = fetcher or PublicEvidenceFetcher()

    def update_news(self, db: Session, lookback_hours: int = 72, limit_per_feed: int = 35, tickers: list[str] | None = None) -> dict:
        asset_query = select(Asset).where(Asset.is_active.is_(True))
        if tickers:
            asset_query = asset_query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
        selected_assets = db.scalars(asset_query).all()
        assets = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
        sources = dedupe_sources(
            [
                *RSS_SOURCES,
                *thematic_web_sources(),
                *asset_web_sources(selected_assets or assets, max_assets=self.settings.max_dynamic_asset_news_feeds),
            ]
        )
        inserted = 0
        linked = 0
        analyzed = 0
        duplicate = 0
        diagnostics: list[dict] = []
        seen_urls: set[str] = set()
        seen_keys: set[str] = set()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        fetched_items = self._fetch_sources_parallel(sources, cutoff, limit_per_feed)
        for diagnostic, items in fetched_items:
            diagnostics.append(diagnostic)
            for item in items:
                self._persist_source_evidence(db, item, assets)
                canonical_key = item["canonical_key"]
                url = item["url"]
                if canonical_key in seen_keys or url in seen_urls:
                    duplicate += 1
                    continue
                seen_keys.add(canonical_key)
                seen_urls.add(url)
                existing = db.scalar(
                    select(NewsArticle).where(or_(NewsArticle.canonical_key == canonical_key, NewsArticle.url == url))
                )
                if existing:
                    duplicate += 1
                    article_stats = self._ensure_article_intelligence(db, existing, assets)
                    linked += article_stats["linked"]
                    analyzed += article_stats["analyzed"]
                    continue
                article = NewsArticle(**item)
                created = True
                try:
                    with db.begin_nested():
                        db.add(article)
                        db.flush()
                except IntegrityError:
                    duplicate += 1
                    created = False
                    article = db.scalar(
                        select(NewsArticle).where(or_(NewsArticle.canonical_key == canonical_key, NewsArticle.url == url))
                    )
                    if not article:
                        continue
                article_stats = self._ensure_article_intelligence(db, article, assets)
                linked += article_stats["linked"]
                analyzed += article_stats["analyzed"]
                if created:
                    inserted += 1
        db.commit()
        source_errors = [item for item in diagnostics if item["status"] != "ok"]
        return {
            "mode": "real_public_news_only",
            "sources_requested": len(sources),
            "sources_ok": len(diagnostics) - len(source_errors),
            "source_errors": source_errors[:20],
            "source_diagnostics": sorted(diagnostics, key=lambda item: (item["status"] != "ok", -item["accepted_items"]))[:80],
            "inserted_articles": inserted,
            "duplicate_articles": duplicate,
            "linked_assets": linked,
            "sentiment_rows": analyzed,
        }

    def _fetch_sources_parallel(self, sources: list[dict], cutoff: datetime, limit: int) -> list[tuple[dict, list[dict]]]:
        workers = max(1, min(self.settings.news_fetch_workers, len(sources)))
        results: list[tuple[dict, list[dict]]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(self._fetch_source, source, cutoff, limit): source for source in sources}
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as exc:
                    source = future_map[future]
                    results.append((source_diagnostic(source, "error", 0, 0, str(exc)), []))
        return results

    def _fetch_source(self, source: dict, cutoff: datetime, limit: int) -> tuple[dict, list[dict]]:
        from app.services.market_clock import utc_naive
        cutoff = utc_naive(cutoff)
        try:
            import xml.etree.ElementTree as ET
            response = self.fetcher.fetch(source["url"], deadline=time.monotonic()+8)
            if response.status != "AVAILABLE":
                return source_diagnostic(source, response.status.lower(), 0, 0, response.error_code or ""), []
            if b"<!doctype" in response.body.lower() or b"<!entity" in response.body.lower():
                return source_diagnostic(source, "error", 0, 0, "BAD_XML"), []
            root = ET.fromstring(response.body)
            if root.tag.rsplit("}", 1)[-1] not in {"rss", "feed", "RDF"}:
                return source_diagnostic(source, "error", 0, 0, "BAD_XML"), []
            parsed = feedparser.parse(response.body)
        except Exception as exc:
            return source_diagnostic(source, "error", 0, 0, "FEED_PARSE_FAILED"), []
        rows: list[dict] = []
        for entry in parsed.entries[:limit]:
            title = clean_text(entry.get("title", ""), 260)
            if not title:
                continue
            summary = clean_text(entry.get("summary", ""), 600)
            published = parse_entry_time(entry)
            published = utc_naive(published) if published else None
            if published and published < cutoff:
                continue
            url = entry.get("link", "") or stable_url(source["url"], title)
            publisher = entry_publisher(entry, parsed.feed.get("title", source["name"]))
            rows.append(
                {
                    "source": clean_text(publisher, 160),
                    "source_url": source["url"],
                    "published_at": published,
                    "created_at": response.observed_at,
                    "title": title,
                    "summary": summary,
                    "body": "",
                    "url": url,
                    "canonical_key": canonical_key(title, url),
                    "quality_score": quality_score(title, summary, source["tier"]),
                    "theme_tags": {
                        "themes": classify_themes(title, summary),
                        "events": classify_events(title, summary),
                        "desk": source["desk"],
                        "tier": source["tier"],
                        "source_reliability": source_reliability(source["tier"]),
                    },
                }
            )
        status = "ok" if rows else "empty"
        return source_diagnostic(source, status, len(parsed.entries), len(rows), ""), rows

    def _persist_source_evidence(self, db, item, assets):
        from app.services.information.contracts import EvidenceLink, ProviderResult, SourceEvidence
        from app.services.information.repository import InformationRepository
        observed = item["created_at"]
        provider = "news:feed:"+hashlib.sha256(item["source_url"].encode()).hexdigest()[:24]
        try:
            evidence = SourceEvidence.create(
                provider=provider, canonical_url=item["url"], language="und",
                published_at=item.get("published_at"), observed_at=observed, available_at=observed,
                payload={"title": item["title"], "text": item["summary"], "publisher": item["source"],
                         "source_capability": "news", "themes": item.get("theme_tags", {})},
                extraction_version="public-news-v1",
            )
        except ValueError:
            return {"inserted": 0, "error_code": "INVALID_EVIDENCE_URL"}
        article = NewsArticle(**item)
        links = tuple(EvidenceLink(evidence.evidence_id, asset.ticker, "issuer", min(.8, score/10),
                                   "heuristic asset alias or theme match; not certified exact issuer", "public-news-v1")
                      for asset, score in self._match_assets(article, assets))
        return InformationRepository().ingest(db, ProviderResult(provider, "AVAILABLE", (evidence,),
                                                                observed_at=observed, links=links))

    def _match_assets(self, article: NewsArticle, assets: list[Asset]) -> list[tuple[Asset, float]]:
        text = f" {article.title} {article.summary} ".lower()
        matches: list[tuple[Asset, float]] = []
        for asset in assets:
            score = 0.0
            ticker = asset.ticker.lower()
            if re.search(rf"[^a-z0-9]{re.escape(ticker)}[^a-z0-9]", text):
                score += 5
            aliases = asset_aliases(asset)
            for alias in aliases:
                if len(alias) > 4 and re.search(rf"[^a-z0-9]{re.escape(alias)}[^a-z0-9]", text):
                    score += 3.5
            for token in asset.name.lower().replace(".", "").replace(",", "").split():
                if len(token) > 4 and token in text:
                    score += 1.5
            if asset.sector.lower() in text:
                score += 1.0
            if asset.industry.lower() and asset.industry.lower() in text:
                score += 1.0
            if score > 0:
                matches.append((asset, score))
        return sorted(matches, key=lambda item: item[1], reverse=True)[:8]

    def _ensure_article_intelligence(self, db: Session, article: NewsArticle, assets: list[Asset]) -> dict:
        analyzed = 0
        linked = 0
        sentiment_exists = db.scalar(
            select(SentimentAnalysis.id)
            .where(SentimentAnalysis.article_id == article.id)
            .limit(1)
        )
        if not sentiment_exists:
            sentiment = self.ai.sentiment.analyze(f"{article.title}. {article.summary}")
            db.add(
                SentimentAnalysis(
                    article_id=article.id,
                    model_name=sentiment["model_name"],
                    label=sentiment["label"],
                    score=sentiment["score"],
                    confidence=sentiment["confidence"],
                    baseline_vader=sentiment["baseline_vader"],
                    raw_payload=sentiment,
                )
            )
            analyzed += 1
        embedding_exists = db.scalar(
            select(EmbeddingVector.id)
            .where(EmbeddingVector.article_id == article.id, EmbeddingVector.model_name == self.ai.embeddings.model_name)
            .limit(1)
        )
        if not embedding_exists:
            vector = self.ai.embeddings.embed_text(f"{article.title}. {article.summary}")
            if vector:
                db.add(EmbeddingVector(article_id=article.id, model_name=self.ai.embeddings.model_name, vector={"values": vector}))
        for asset, relevance in self._match_assets(article, assets):
            link_exists = db.scalar(
                select(NewsAssetLink.id)
                .where(NewsAssetLink.article_id == article.id, NewsAssetLink.asset_id == asset.id)
                .limit(1)
            )
            if link_exists:
                continue
            try:
                with db.begin_nested():
                    db.add(NewsAssetLink(article_id=article.id, asset_id=asset.id, relevance_score=relevance))
                    db.flush()
                linked += 1
            except IntegrityError:
                continue
        return {"analyzed": analyzed, "linked": linked}


def clean_text(value: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def parse_entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def canonical_key(title: str, url: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    digest = hashlib.sha256(f"{normalized}|{url}".encode("utf-8")).hexdigest()[:20]
    return f"{normalized[:180]}:{digest}"


def stable_url(feed_url: str, title: str) -> str:
    return f"{feed_url}#{hashlib.sha1(title.encode('utf-8')).hexdigest()[:12]}"


def classify_themes(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    themes = [theme for theme, terms in THEME_KEYWORDS.items() if any(term in text for term in terms)]
    return themes or ["Market Structure"]


def classify_events(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    return [event for event, terms in EVENT_KEYWORDS.items() if any(term in text for term in terms)]


def source_reliability(tier: int) -> str:
    if tier <= 1:
        return "primary_or_tier_1"
    if tier == 2:
        return "trusted_financial_press"
    if tier == 3:
        return "specialist_or_sector_source"
    return "broad_web_source"


def asset_aliases(asset: Asset) -> list[str]:
    raw = [
        asset.name,
        asset.name.replace(" Inc.", ""),
        asset.name.replace(" Corporation", ""),
        asset.name.replace(" Corp.", ""),
        asset.name.replace(" plc", ""),
        asset.name.replace(" SE", ""),
        asset.name.replace(" AG", ""),
    ]
    aliases = []
    for item in raw:
        cleaned = re.sub(r"[^a-z0-9 ]+", " ", item.lower()).strip()
        cleaned = re.sub(r"\b(the|inc|corp|corporation|plc|se|ag|sa|nv|ltd|class|ordinary|shares|etf|trust)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > 4:
            aliases.append(cleaned)
    return list(dict.fromkeys(aliases))


def quality_score(title: str, summary: str, tier: int) -> float:
    score = 35 + max(0, 4 - int(tier)) * 10
    score += min(len(summary) / 80, 10)
    score += 8 if any(word in f"{title} {summary}".lower() for word in ["earnings", "guidance", "fed", "revenue", "margins", "forecast"]) else 0
    return round(max(0, min(100, score)), 1)


def dedupe_sources(sources: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for source in sources:
        if source["url"] in seen:
            continue
        seen.add(source["url"])
        output.append(source)
    return output


def entry_publisher(entry, default: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        title = source.get("title")
        if title:
            return title
    return default


def source_diagnostic(source: dict, status: str, fetched_items: int, accepted_items: int, error: str) -> dict:
    return {
        "name": source["name"],
        "desk": source.get("desk", ""),
        "kind": source.get("kind", "rss"),
        "status": status,
        "fetched_items": fetched_items,
        "accepted_items": accepted_items,
        "error": error[:220],
    }
