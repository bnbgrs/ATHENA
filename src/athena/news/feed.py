"""Dependency-light, fail-closed RSS/Atom parsing for already-captured feed bytes."""

from __future__ import annotations

import email.utils
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

_MAX_FEED_BYTES = 4 * 1024 * 1024
_MAX_ITEMS = 500
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class FeedParseError(RuntimeError):
    """Raised when captured feed bytes cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class FeedItem:
    canonical_url: str
    url_hash: bytes
    title: str
    summary: str
    published_at_us: int | None


def canonicalize_url(value: str, *, base_url: str | None = None) -> str:
    raw = value.strip()
    if base_url is not None:
        raw = urljoin(base_url, raw)
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise FeedParseError("Feed item URL must be absolute HTTP(S).")
    if parsed.username is not None or parsed.password is not None:
        raise FeedParseError("Feed item URL must not contain credentials.")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    port = parsed.port
    default = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port in {None, default} else f"{host}:{port}"
    query = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        lower = key.lower()
        if lower.startswith("utm_") or lower in _TRACKING_KEYS:
            continue
        query.append((key, val))
    query.sort()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query), ""))


def parse_feed(payload: bytes, *, feed_url: str) -> tuple[FeedItem, ...]:
    if len(payload) > _MAX_FEED_BYTES:
        raise FeedParseError("Feed exceeds ATHENA's bounded parser size.")
    upper = payload[:8192].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise FeedParseError("DTD/entity declarations are prohibited in news feeds.")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise FeedParseError("Captured feed is not valid bounded XML.") from exc

    root_name = _local(root.tag).lower()
    items: list[FeedItem] = []
    if root_name == "rss" or root.find("channel") is not None:
        nodes = root.findall("./channel/item")
        for node in nodes[:_MAX_ITEMS]:
            link = _text(node, "link")
            if not link:
                continue
            items.append(
                _item(
                    link,
                    title=_text(node, "title"),
                    summary=_text(node, "description"),
                    published=_text(node, "pubDate") or _text(node, "date"),
                    feed_url=feed_url,
                )
            )
    elif root_name == "feed":
        ns = "{http://www.w3.org/2005/Atom}"
        nodes = root.findall(f"{ns}entry") or root.findall("entry")
        for node in nodes[:_MAX_ITEMS]:
            link = ""
            for link_node in list(node):
                if _local(link_node.tag).lower() != "link":
                    continue
                rel = link_node.attrib.get("rel", "alternate")
                href = link_node.attrib.get("href", "")
                if href and rel in {"alternate", ""}:
                    link = href
                    break
            if not link:
                continue
            items.append(
                _item(
                    link,
                    title=_child_text(node, "title"),
                    summary=_child_text(node, "summary") or _child_text(node, "content"),
                    published=_child_text(node, "published") or _child_text(node, "updated"),
                    feed_url=feed_url,
                )
            )
    else:
        raise FeedParseError("Captured XML is neither RSS nor Atom.")

    dedup: dict[bytes, FeedItem] = {}
    for item in items:
        dedup.setdefault(item.url_hash, item)
    return tuple(dedup.values())



class _WebDiscoveryParser(HTMLParser):
    """Bounded semantic-link collector for already-captured publisher pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.headline_depth = 0
        self.active_href: str | None = None
        self.active_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower_tag = tag.casefold()
        if lower_tag == "article":
            self.article_depth += 1
        if lower_tag in {"h1", "h2", "h3"}:
            self.headline_depth += 1
        if lower_tag != "a" or self.active_href is not None:
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        href = attributes.get("href", "").strip()
        if not href:
            return
        marker = " ".join(
            (
                attributes.get("class", ""),
                attributes.get("rel", ""),
                attributes.get("data-testid", ""),
            )
        ).casefold()
        href_lower = href.casefold()
        articleish = (
            self.article_depth > 0
            or self.headline_depth > 0
            or any(
                token in marker
                for token in ("article", "headline", "story", "bookmark")
            )
            or any(token in href_lower for token in ("/article/", "/story/", "/news/"))
        )
        if articleish:
            self.active_href = href
            self.active_text = []

    def handle_data(self, data: str) -> None:
        if self.active_href is not None:
            self.active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.casefold()
        if lower_tag == "a" and self.active_href is not None:
            if len(self.links) < _MAX_ITEMS * 4:
                self.links.append((self.active_href, _clean(" ".join(self.active_text))))
            self.active_href = None
            self.active_text = []
        if lower_tag == "article" and self.article_depth > 0:
            self.article_depth -= 1
        if lower_tag in {"h1", "h2", "h3"} and self.headline_depth > 0:
            self.headline_depth -= 1


def parse_discovery_payload(
    payload: bytes, *, source_url: str
) -> tuple[FeedItem, ...]:
    """Parse a captured RSS/Atom feed, News sitemap, or conservative HTML page."""
    if len(payload) > _MAX_FEED_BYTES:
        raise FeedParseError("Discovery payload exceeds ATHENA's bounded parser size.")
    prefix = payload[:8192].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or b"<html" in prefix:
        return parse_web_page(payload, source_url=source_url)
    try:
        return parse_feed(payload, feed_url=source_url)
    except FeedParseError as feed_error:
        try:
            return parse_news_sitemap(payload, source_url=source_url)
        except FeedParseError:
            raise feed_error from None


def parse_news_sitemap(
    payload: bytes, *, source_url: str
) -> tuple[FeedItem, ...]:
    """Extract article candidates from an already-captured XML URL set."""
    if len(payload) > _MAX_FEED_BYTES:
        raise FeedParseError("News sitemap exceeds ATHENA's bounded parser size.")
    upper = payload[:8192].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise FeedParseError("DTD/entity declarations are prohibited in news discovery XML.")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise FeedParseError("Captured discovery XML is invalid.") from exc
    if _local(root.tag).casefold() != "urlset":
        raise FeedParseError("Captured XML is not a supported News sitemap URL set.")

    source_host = _normalized_host(source_url)
    if source_host is None:
        raise FeedParseError("News discovery source URL has no valid host.")
    candidates: dict[bytes, FeedItem] = {}
    for node in list(root)[:_MAX_ITEMS]:
        if _local(node.tag).casefold() != "url":
            continue
        raw_url = _descendant_text(node, "loc")
        if not raw_url:
            continue
        try:
            canonical = canonicalize_url(raw_url, base_url=source_url)
        except FeedParseError:
            continue
        if _normalized_host(canonical) != source_host:
            continue
        title = _clean(_descendant_text(node, "title"))[:1000]
        published = _descendant_text(node, "publication_date")
        url_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        candidates.setdefault(
            url_hash,
            FeedItem(
                canonical_url=canonical,
                url_hash=url_hash,
                title=title or canonical,
                summary="",
                published_at_us=_parse_time(published),
            ),
        )
    return tuple(candidates.values())


def parse_web_page(payload: bytes, *, source_url: str) -> tuple[FeedItem, ...]:
    """Extract same-host article-like links from an immutable captured HTML page."""
    if len(payload) > _MAX_FEED_BYTES:
        raise FeedParseError("News web page exceeds ATHENA's bounded parser size.")
    source_host = _normalized_host(source_url)
    if source_host is None:
        raise FeedParseError("News discovery source URL has no valid host.")
    parser = _WebDiscoveryParser()
    try:
        parser.feed(payload.decode("utf-8", errors="replace"))
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise FeedParseError("Captured News HTML could not be parsed safely.") from exc

    candidates: dict[bytes, FeedItem] = {}
    for raw_url, raw_title in parser.links:
        try:
            canonical = canonicalize_url(raw_url, base_url=source_url)
        except FeedParseError:
            continue
        if _normalized_host(canonical) != source_host:
            continue
        title = _clean(raw_title)[:1000]
        if len(title) < 5:
            continue
        url_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        candidates.setdefault(
            url_hash,
            FeedItem(
                canonical_url=canonical,
                url_hash=url_hash,
                title=title,
                summary="",
                published_at_us=None,
            ),
        )
        if len(candidates) >= _MAX_ITEMS:
            break
    return tuple(candidates.values())


def _normalized_host(value: str) -> str | None:
    try:
        host = urlsplit(value).hostname
    except ValueError:
        return None
    if not host:
        return None
    try:
        return host.encode("idna").decode("ascii").casefold().rstrip(".")
    except UnicodeError:
        return None


def _descendant_text(node: ElementTree.Element, name: str) -> str:
    wanted = name.casefold()
    for descendant in node.iter():
        if _local(descendant.tag).casefold() == wanted and descendant.text:
            return descendant.text.strip()
    return ""

def _item(
    link: str,
    *,
    title: str,
    summary: str,
    published: str,
    feed_url: str,
) -> FeedItem:
    url = canonicalize_url(link, base_url=feed_url)
    return FeedItem(
        canonical_url=url,
        url_hash=hashlib.sha256(url.encode("utf-8")).digest(),
        title=_clean(title)[:1000],
        summary=_clean(summary)[:4000],
        published_at_us=_parse_time(published),
    )


def _parse_time(value: str) -> int | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _text(node: ElementTree.Element, name: str) -> str:
    child = node.find(name)
    return "" if child is None or child.text is None else child.text


def _child_text(node: ElementTree.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag).lower() == name.lower():
            return "" if child.text is None else child.text
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(value: str) -> str:
    return " ".join(value.split())
