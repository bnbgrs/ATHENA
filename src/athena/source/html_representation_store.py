"""Deterministic cleaned text and DOM-derived structure extraction for HTML Sources."""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from athena.source.models import SourceRepresentationStructureType
from athena.source.representation_store import (
    PreparedTextRepresentation,
    StoredRepresentationBlob,
    TextRepresentationStore,
)
from athena.storage.paths import RuntimePaths

_MAX_HTML_BYTES = 64 * 1024 * 1024
_MAX_TREE_DEPTH = 256
_MAX_NODES = 500_000
_MAX_ATTRIBUTE_LENGTH = 64 * 1024
_BLOCK_SEPARATOR = "\n\n"
_CELL_BLOCK_SEPARATOR = "\n"
_CELL_SEPARATOR = "\t"
_ROW_SEPARATOR = "\n"
_EXCLUDED_TAGS = frozenset(
    {
        "script",
        "style",
        "template",
        "noscript",
        "svg",
        "canvas",
        "iframe",
    }
)

_BOILERPLATE_TAGS = frozenset(
    {
        "aside",
        "dialog",
        "footer",
        "form",
        "nav",
    }
)

_BOILERPLATE_ROLES = frozenset(
    {
        "complementary",
        "contentinfo",
        "navigation",
        "search",
    }
)

_BOILERPLATE_ATTR_NAMES = (
    "id",
    "class",
    "aria-label",
    "data-testid",
    "data-component",
    "data-module",
    "data-content-name",
    "data-cname",
)

_BOILERPLATE_TOKENS = frozenset(
    {
        "ad",
        "ads",
        "advert",
        "advertisement",
        "advertiser",
        "affiliate",
        "commerce",
        "comment",
        "comments",
        "newsletter",
        "popular",
        "promo",
        "promotion",
        "recirc",
        "recirculation",
        "recommendation",
        "recommended",
        "related",
        "share",
        "sidebar",
        "sponsor",
        "sponsored",
        "subscribe",
        "subscription",
    }
)

_BOILERPLATE_ATTR_PHRASES = (
    "advertiser-content",
    "advertiser content",
    "from-our-sponsor",
    "from our sponsor",
    "most-popular",
    "most popular",
    "native-ad",
    "native ad",
    "more-stories",
    "more stories",
    "read-next",
    "read next",
    "related-stories",
    "related stories",
    "recommended-stories",
    "recommended stories",
    "sponsored-content",
    "sponsored content",
)

_BOILERPLATE_COMPACT_PHRASES = (
    "advertisercontent",
    "mostpopular",
    "nativead",
    "morestories",
    "readnext",
    "relatedstories",
    "recommendedstories",
    "sponsoredcontent",
)

_BOILERPLATE_HEADINGS = frozenset(
    {
        "advertiser content",
        "comments",
        "from our sponsor",
        "more stories",
        "most popular",
        "newsletter",
        "recommended",
        "recommended stories",
        "related",
        "related stories",
        "sponsored content",
    }
)

_BOILERPLATE_HEADING_PREFIXES = (
    "also read",
    "more from ",
    "read next",
    "recommended for ",
    "you may also like",
)

_ATTR_TOKEN_RE = re.compile(
    r"[^a-z0-9]+"
)

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_CONTAINER_TAGS = frozenset(
    {
        "html",
        "body",
        "main",
        "article",
        "section",
        "div",
        "header",
        "footer",
        "aside",
        "nav",
        "form",
        "fieldset",
        "details",
        "dialog",
        "figure",
        "figcaption",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
    }
)
_PARAGRAPH_TAGS = frozenset({"p", "pre", "blockquote", "address"})
_TABLE_SECTION_TAGS = frozenset({"thead", "tbody", "tfoot"})
_INLINE_BREAK_TAGS = frozenset({"br"})
_META_CHARSET_RE = re.compile(
    br"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([A-Za-z0-9._:-]+)",
    flags=re.IGNORECASE,
)
_META_CONTENT_TYPE_RE = re.compile(
    br"<meta\b[^>]*\bcontent\s*=\s*[\"'][^\"']*charset\s*=\s*([A-Za-z0-9._:-]+)[^\"']*[\"']",
    flags=re.IGNORECASE,
)
_ALLOWED_ENCODINGS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "us-ascii": "ascii",
    "ascii": "ascii",
    "windows-1252": "cp1252",
    "cp1252": "cp1252",
    "iso-8859-1": "latin-1",
    "latin-1": "latin-1",
    "latin1": "latin-1",
}


class HtmlRepresentationError(RuntimeError):
    """Base error for native HTML representation work."""


class UnsupportedHtmlSourceError(HtmlRepresentationError):
    """Raised when a Source is not supported by the native HTML parser."""


class HtmlTextUnavailableError(HtmlRepresentationError):
    """Raised when HTML contains no usable readable text."""


@dataclass(frozen=True, slots=True)
class HtmlStructureSpan:
    structure_index: int
    structure_type: SourceRepresentationStructureType
    path: str
    parent_index: int | None
    start_offset: int
    end_offset: int
    content_sha256: bytes
    metadata_json: str


@dataclass(frozen=True, slots=True)
class PreparedHtmlTextRepresentation:
    staging_path: Path
    byte_length: int
    content_sha256: bytes
    structures: tuple[HtmlStructureSpan, ...]


@dataclass(slots=True)
class _HtmlNode:
    tag: str
    attrs: tuple[tuple[str, str | None], ...]
    parent: _HtmlNode | None
    children: list[_HtmlNode | str] = field(default_factory=list)
    path: str = ""

    def attr(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.attrs:
            if key.lower() == lowered:
                return value
        return None


@dataclass(slots=True)
class _PendingStructure:
    structure_type: SourceRepresentationStructureType
    path: str
    parent_index: int | None
    start_offset: int
    end_offset: int | None
    metadata: dict[str, object]


class _TextAndStructureBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.offset = 0
        self.structures: list[_PendingStructure] = []

    def append(self, value: str) -> None:
        if not value:
            return
        self.parts.append(value)
        self.offset += len(value)

    def begin(
        self,
        structure_type: SourceRepresentationStructureType,
        *,
        path: str,
        parent_index: int | None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        index = len(self.structures)
        self.structures.append(
            _PendingStructure(
                structure_type=structure_type,
                path=path,
                parent_index=parent_index,
                start_offset=self.offset,
                end_offset=None,
                metadata=dict(metadata or {}),
            )
        )
        return index

    def end(self, index: int) -> None:
        pending = self.structures[index]
        if pending.end_offset is not None:
            raise RuntimeError("HTML structure span was finalized twice.")
        pending.end_offset = self.offset

    def finish(self) -> tuple[str, tuple[HtmlStructureSpan, ...]]:
        text = "".join(self.parts)
        records: list[HtmlStructureSpan] = []
        for index, pending in enumerate(self.structures):
            if pending.end_offset is None:
                raise RuntimeError("HTML structure span was not finalized.")
            fragment = text[pending.start_offset : pending.end_offset]
            records.append(
                HtmlStructureSpan(
                    structure_index=index,
                    structure_type=pending.structure_type,
                    path=pending.path,
                    parent_index=pending.parent_index,
                    start_offset=pending.start_offset,
                    end_offset=pending.end_offset,
                    content_sha256=hashlib.sha256(fragment.encode("utf-8")).digest(),
                    metadata_json=json.dumps(
                        pending.metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                )
            )
        return text, tuple(records)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode(tag="#document", attrs=(), parent=None, path="")
        self.stack: list[_HtmlNode] = [self.root]
        self.node_count = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        normalized_attrs = _validate_attrs(attrs)
        node = _HtmlNode(
            tag=normalized_tag,
            attrs=normalized_attrs,
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(node)
        self._count_node()
        if normalized_tag not in _VOID_TAGS:
            if len(self.stack) >= _MAX_TREE_DEPTH:
                raise HtmlRepresentationError("HTML nesting exceeds the native parser safety limit.")
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_attrs = _validate_attrs(attrs)
        node = _HtmlNode(
            tag=tag.lower(),
            attrs=normalized_attrs,
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(node)
        self._count_node()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == normalized:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self.stack[-1].children.append(data)

    def handle_comment(self, data: str) -> None:
        # Comments remain immutable in the Raw Archive. They are deliberately
        # absent from cleaned readable text and therefore cannot become parser
        # directives or hidden model instructions.
        return

    def unknown_decl(self, data: str) -> None:
        return

    def _count_node(self) -> None:
        self.node_count += 1
        if self.node_count > _MAX_NODES:
            raise HtmlRepresentationError("HTML node count exceeds the native parser safety limit.")


class HtmlNativeTextRepresentationStore:
    """Extract cleaned readable HTML text plus retained DOM-derived structure."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self._text_store = TextRepresentationStore(paths)

    def extract(
        self,
        source_path: Path,
        *,
        primary_article: bool = False,
    ) -> PreparedHtmlTextRepresentation:
        staging_dir = (
            self.paths.spool_root
            / "representations"
            / "staging"
        )
        staging_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        staging_path = (
            staging_dir
            / f"html-text-{secrets.token_hex(16)}.partial"
        )

        try:
            raw = _read_html_bytes(
                source_path
            )

            text, structures = (
                _extract_html_text_and_structures(
                    raw,
                    primary_article=(
                        primary_article
                    ),
                )
            )

            encoded = text.encode(
                "utf-8"
            )

            with staging_path.open(
                "xb"
            ) as target:
                target.write(
                    encoded
                )
                target.flush()
                os.fsync(
                    target.fileno()
                )

            return PreparedHtmlTextRepresentation(
                staging_path=staging_path,
                byte_length=len(
                    encoded
                ),
                content_sha256=(
                    hashlib.sha256(
                        encoded
                    ).digest()
                ),
                structures=structures,
            )

        except Exception:
            staging_path.unlink(
                missing_ok=True
            )
            raise


    def discard(self, prepared: PreparedHtmlTextRepresentation) -> None:
        prepared.staging_path.unlink(missing_ok=True)

    def commit(self, prepared: PreparedHtmlTextRepresentation) -> StoredRepresentationBlob:
        base = PreparedTextRepresentation(
            staging_path=prepared.staging_path,
            byte_length=prepared.byte_length,
            content_sha256=prepared.content_sha256,
        )
        return self._text_store.commit(base)


def extract_html_text_bytes(
    payload: bytes,
    *,
    primary_article: bool = False,
) -> str:
    """Extract cleaned HTML text directly from plaintext bytes in memory."""

    text, _structures = (
        _extract_html_text_and_structures(
            payload,
            primary_article=primary_article,
        )
    )

    return text


def _extract_html_text_and_structures(
    payload: bytes,
    *,
    primary_article: bool,
) -> tuple[
    str,
    tuple[HtmlStructureSpan, ...],
]:
    _validate_html_payload(
        payload
    )

    decoded, encoding = _decode_html(
        payload
    )

    parser = _TreeBuilder()

    try:
        parser.feed(
            decoded
        )
        parser.close()

    except (
        RecursionError,
        ValueError,
    ) as exc:
        raise HtmlRepresentationError(
            "Cannot parse HTML source safely."
        ) from exc

    _assign_dom_paths(
        parser.root
    )

    builder = (
        _TextAndStructureBuilder()
    )

    title = _document_title(
        parser.root
    )

    emitted = False

    if title is not None:
        title_node, title_text = title

        title_index = builder.begin(
            SourceRepresentationStructureType.HEADING,
            path=title_node.path,
            parent_index=None,
            metadata={
                "heading_level": 1,
                "html_tag": "title",
                "document_title": True,
                "source_encoding": encoding,
            },
        )

        builder.append(
            title_text
        )
        builder.end(
            title_index
        )

        emitted = True

    body = _first_element(
        parser.root,
        "body",
    )

    if primary_article:
        flow_root = (
            _select_primary_article_flow_root(
                parser.root
            )
        )

        _prune_article_boilerplate(
            flow_root
        )

    else:
        flow_root = (
            body
            if body is not None
            else parser.root
        )

    if (
        emitted
        and _has_readable_flow(
            flow_root
        )
    ):
        builder.append(
            _BLOCK_SEPARATOR
        )

    _render_flow_container(
        flow_root,
        builder=builder,
        parent_index=None,
        separator=_BLOCK_SEPARATOR,
    )

    text, structures = (
        builder.finish()
    )

    if not text.strip():
        raise HtmlTextUnavailableError(
            "HTML contains no usable "
            "cleaned readable text."
        )

    if not structures:
        raise HtmlTextUnavailableError(
            "HTML contains no retained "
            "readable structure."
        )

    return (
        text,
        structures,
    )


def _validate_html_payload(
    payload: bytes,
) -> None:
    if len(payload) > _MAX_HTML_BYTES:
        raise HtmlRepresentationError(
            "HTML source exceeds the "
            "native parser safety limit."
        )

    if b"\x00" in payload:
        raise HtmlRepresentationError(
            "HTML source contains NUL bytes "
            "and is not accepted as text HTML."
        )


def _read_html_bytes(
    path: Path,
) -> bytes:
    try:
        size = path.stat().st_size

    except OSError as exc:
        raise HtmlRepresentationError(
            "Cannot stat HTML source blob."
        ) from exc

    if size > _MAX_HTML_BYTES:
        raise HtmlRepresentationError(
            "HTML source exceeds the "
            "native parser safety limit."
        )

    try:
        payload = path.read_bytes()

    except OSError as exc:
        raise HtmlRepresentationError(
            "Cannot read HTML source blob."
        ) from exc

    _validate_html_payload(
        payload
    )

    return payload



def _decode_html(payload: bytes) -> tuple[str, str]:
    if payload.startswith(codecs.BOM_UTF8):
        try:
            return payload.decode("utf-8-sig", errors="strict"), "utf-8"
        except UnicodeDecodeError as exc:
            raise HtmlRepresentationError("HTML UTF-8 BOM content is invalid UTF-8.") from exc

    probe = payload[:8192]
    match = _META_CHARSET_RE.search(probe) or _META_CONTENT_TYPE_RE.search(probe)
    declared = match.group(1).decode("ascii", errors="ignore").lower() if match else "utf-8"
    codec = _ALLOWED_ENCODINGS.get(declared)
    if codec is None:
        raise UnsupportedHtmlSourceError(
            f"HTML declares unsupported deterministic charset {declared!r}."
        )
    try:
        return payload.decode(codec, errors="strict"), declared
    except UnicodeDecodeError as exc:
        raise HtmlRepresentationError(
            f"HTML bytes are invalid for declared charset {declared!r}."
        ) from exc


def _validate_attrs(attrs: list[tuple[str, str | None]]) -> tuple[tuple[str, str | None], ...]:
    result: list[tuple[str, str | None]] = []
    for key, value in attrs:
        normalized_key = key.lower()
        if len(normalized_key) > _MAX_ATTRIBUTE_LENGTH:
            raise HtmlRepresentationError("HTML attribute name exceeds the safety limit.")
        if value is not None and len(value) > _MAX_ATTRIBUTE_LENGTH:
            raise HtmlRepresentationError("HTML attribute value exceeds the safety limit.")
        result.append((normalized_key, value))
    return tuple(result)


def _assign_dom_paths(root: _HtmlNode) -> None:
    def walk(parent: _HtmlNode) -> None:
        counts: dict[str, int] = {}
        for child in parent.children:
            if isinstance(child, str):
                continue
            counts[child.tag] = counts.get(child.tag, 0) + 1
            child.path = f"{parent.path}/{child.tag}[{counts[child.tag]}]"
            walk(child)

    walk(root)


def _first_element(root: _HtmlNode, tag: str) -> _HtmlNode | None:
    for child in root.children:
        if isinstance(child, _HtmlNode):
            if child.tag == tag:
                return child
            found = _first_element(child, tag)
            if found is not None:
                return found
    return None


def _document_title(root: _HtmlNode) -> tuple[_HtmlNode, str] | None:
    head = _first_element(root, "head")
    if head is None:
        return None
    title = _first_element(head, "title")
    if title is None:
        return None
    text, _links = _inline_text_and_links(title)
    cleaned = text.strip()
    return (title, cleaned) if cleaned else None


def _node_has_attr(
    node: _HtmlNode,
    name: str,
) -> bool:
    lowered = name.lower()

    return any(
        key.lower() == lowered
        for key, _value in node.attrs
    )


def _attr_value_has_boilerplate_marker(
    value: str,
) -> bool:
    normalized = value.strip().lower()

    if not normalized:
        return False

    if any(
        phrase in normalized
        for phrase in _BOILERPLATE_ATTR_PHRASES
    ):
        return True

    compact = re.sub(
        r"[^a-z0-9]+",
        "",
        normalized,
    )

    if any(
        phrase in compact
        for phrase in _BOILERPLATE_COMPACT_PHRASES
    ):
        return True

    tokens = {
        token
        for token in _ATTR_TOKEN_RE.split(
            normalized
        )
        if token
    }

    return bool(
        tokens.intersection(
            _BOILERPLATE_TOKENS
        )
    )


def _plain_node_text(
    node: _HtmlNode,
) -> str:
    parts: list[str] = []

    def collect(
        item: _HtmlNode | str,
    ) -> None:
        if isinstance(item, str):
            parts.append(item)
            return

        if (
            item.tag in _EXCLUDED_TAGS
            or item.tag == "head"
        ):
            return

        for child in item.children:
            collect(child)

    for child in node.children:
        collect(child)

    return re.sub(
        r"\s+",
        " ",
        "".join(parts),
    ).strip()


def _first_heading_text(
    node: _HtmlNode,
) -> str | None:
    for child in node.children:
        if not isinstance(
            child,
            _HtmlNode,
        ):
            continue

        if child.tag in _EXCLUDED_TAGS:
            continue

        if (
            _heading_level(child.tag)
            is not None
        ):
            text = _plain_node_text(child)

            if text:
                return text

        nested = _first_heading_text(
            child
        )

        if nested:
            return nested

    return None


def _heading_marks_boilerplate(
    node: _HtmlNode,
) -> bool:
    if node.tag not in {
        "section",
        "div",
    }:
        return False

    heading = _first_heading_text(
        node
    )

    if heading is None:
        return False

    normalized = (
        heading
        .casefold()
        .strip()
    )

    if normalized in _BOILERPLATE_HEADINGS:
        return True

    return any(
        normalized.startswith(prefix)
        for prefix
        in _BOILERPLATE_HEADING_PREFIXES
    )


def _is_article_boilerplate_node(
    node: _HtmlNode,
) -> bool:
    if node.tag in _BOILERPLATE_TAGS:
        return True

    if _node_has_attr(
        node,
        "hidden",
    ):
        return True

    aria_hidden = node.attr(
        "aria-hidden"
    )

    if (
        aria_hidden is not None
        and aria_hidden.strip().lower()
        == "true"
    ):
        return True

    role = node.attr("role")

    if (
        role is not None
        and role.strip().lower()
        in _BOILERPLATE_ROLES
    ):
        return True

    for attribute_name in (
        _BOILERPLATE_ATTR_NAMES
    ):
        value = node.attr(
            attribute_name
        )

        if (
            value is not None
            and _attr_value_has_boilerplate_marker(
                value
            )
        ):
            return True

    return _heading_marks_boilerplate(
        node
    )


def _iter_article_candidates(
    root: _HtmlNode,
    tag: str,
) -> Iterator[_HtmlNode]:
    for child in root.children:
        if not isinstance(
            child,
            _HtmlNode,
        ):
            continue

        if (
            child.tag in _EXCLUDED_TAGS
            or child.tag == "head"
            or _is_article_boilerplate_node(
                child
            )
        ):
            continue

        if child.tag == tag:
            yield child

        yield from _iter_article_candidates(
            child,
            tag,
        )


def _article_visible_character_count(
    node: _HtmlNode,
) -> int:
    total = 0

    for child in node.children:
        if isinstance(child, str):
            total += len(
                re.sub(
                    r"\s+",
                    " ",
                    child,
                ).strip()
            )
            continue

        if (
            child.tag in _EXCLUDED_TAGS
            or child.tag == "head"
            or _is_article_boilerplate_node(
                child
            )
        ):
            continue

        total += (
            _article_visible_character_count(
                child
            )
        )

    return total


def _article_contains_h1(
    node: _HtmlNode,
) -> bool:
    for child in node.children:
        if not isinstance(
            child,
            _HtmlNode,
        ):
            continue

        if (
            child.tag in _EXCLUDED_TAGS
            or _is_article_boilerplate_node(
                child
            )
        ):
            continue

        if child.tag == "h1":
            return True

        if _article_contains_h1(
            child
        ):
            return True

    return False


def _article_root_score(
    node: _HtmlNode,
) -> tuple[int, int]:
    return (
        (
            1
            if _article_contains_h1(node)
            else 0
        ),
        _article_visible_character_count(
            node
        ),
    )


def _best_article_candidate(
    candidates: tuple[_HtmlNode, ...],
) -> _HtmlNode:
    if not candidates:
        raise RuntimeError(
            "Article candidate set is empty."
        )

    best_index, best = max(
        enumerate(candidates),
        key=lambda item: (
            _article_root_score(
                item[1]
            ),
            -item[0],
        ),
    )

    del best_index
    return best


def _select_primary_article_flow_root(
    root: _HtmlNode,
) -> _HtmlNode:
    body = _first_element(
        root,
        "body",
    )

    search_root = (
        body
        if body is not None
        else root
    )

    articles = tuple(
        _iter_article_candidates(
            search_root,
            "article",
        )
    )

    if articles:
        return _best_article_candidate(
            articles
        )

    mains = tuple(
        _iter_article_candidates(
            search_root,
            "main",
        )
    )

    if mains:
        return _best_article_candidate(
            mains
        )

    return search_root


def _prune_article_boilerplate(
    node: _HtmlNode,
) -> None:
    retained: list[
        _HtmlNode | str
    ] = []

    for child in node.children:
        if isinstance(child, str):
            retained.append(child)
            continue

        if (
            child.tag in _EXCLUDED_TAGS
            or child.tag == "head"
            or _is_article_boilerplate_node(
                child
            )
        ):
            continue

        _prune_article_boilerplate(
            child
        )

        retained.append(child)

    node.children = retained


def _has_readable_flow(node: _HtmlNode) -> bool:
    text, _links = _inline_text_and_links(node, stop_at_blocks=True)
    if text.strip():
        return True
    for child in node.children:
        if not isinstance(child, _HtmlNode) or child.tag in _EXCLUDED_TAGS or child.tag == "head":
            continue
        if child.tag == "table" or _is_semantic_block(child) or _has_readable_flow(child):
            return True
    return False


def _is_semantic_block(node: _HtmlNode) -> bool:
    return node.tag in _PARAGRAPH_TAGS or node.tag == "li" or _heading_level(node.tag) is not None


def _is_container(node: _HtmlNode) -> bool:
    if node.tag in _CONTAINER_TAGS:
        return True
    return any(
        isinstance(child, _HtmlNode)
        and (child.tag == "table" or _is_semantic_block(child) or child.tag in _CONTAINER_TAGS)
        for child in node.children
    )


def _render_flow_container(
    container: _HtmlNode,
    *,
    builder: _TextAndStructureBuilder,
    parent_index: int | None,
    separator: str,
) -> bool:
    emitted_any = False
    inline_group: list[_HtmlNode | str] = []
    synthetic_index = 0

    def emit_separator_if_needed() -> None:
        if emitted_any:
            builder.append(separator)

    def flush_inline() -> None:
        nonlocal emitted_any, synthetic_index
        if not inline_group:
            return
        text, links = _inline_group_text_and_links(inline_group)
        inline_group.clear()
        if not text.strip():
            return
        emit_separator_if_needed()
        synthetic_index += 1
        index = builder.begin(
            SourceRepresentationStructureType.PARAGRAPH,
            path=f"{container.path or '/document'}/text()[{synthetic_index}]",
            parent_index=parent_index,
            metadata={
                "html_tag": "#text-flow",
                **({"links": links} if links else {}),
            },
        )
        builder.append(text)
        builder.end(index)
        emitted_any = True

    for child in container.children:
        if isinstance(child, str):
            inline_group.append(child)
            continue
        if child.tag == "head" or child.tag in _EXCLUDED_TAGS or child.tag in {"hr", "meta", "link", "base"}:
            continue
        if child.tag == "table":
            flush_inline()
            if _table_has_text(child):
                emit_separator_if_needed()
                _render_table(child, builder=builder, parent_index=parent_index)
                emitted_any = True
            continue
        if _is_semantic_block(child):
            flush_inline()
            text, links = _inline_text_and_links(child, stop_at_blocks=False)
            if not text.strip():
                continue
            emit_separator_if_needed()
            _render_semantic_block(
                child,
                text=text,
                links=links,
                builder=builder,
                parent_index=parent_index,
            )
            emitted_any = True
            continue
        if _is_container(child):
            flush_inline()
            if emitted_any and _has_readable_flow(child):
                builder.append(separator)
            child_emitted = _render_flow_container(
                child,
                builder=builder,
                parent_index=parent_index,
                separator=separator,
            )
            emitted_any = emitted_any or child_emitted
            continue
        inline_group.append(child)

    flush_inline()
    return emitted_any


def _render_semantic_block(
    node: _HtmlNode,
    *,
    text: str,
    links: list[dict[str, object]],
    builder: _TextAndStructureBuilder,
    parent_index: int | None,
) -> None:
    heading_level = _heading_level(node.tag)
    metadata: dict[str, object] = {"html_tag": node.tag}
    if links:
        metadata["links"] = links
    if heading_level is not None:
        structure_type = SourceRepresentationStructureType.HEADING
        metadata["heading_level"] = heading_level
    elif node.tag == "li":
        structure_type = SourceRepresentationStructureType.LIST_ITEM
        list_ancestor = _nearest_list_ancestor(node)
        if list_ancestor is not None:
            metadata["list_kind"] = list_ancestor.tag
            metadata["list_level"] = _list_depth(node) - 1
    else:
        structure_type = SourceRepresentationStructureType.PARAGRAPH
        if node.tag == "pre":
            metadata["preformatted"] = True
    index = builder.begin(
        structure_type,
        path=node.path,
        parent_index=parent_index,
        metadata=metadata,
    )
    builder.append(text)
    builder.end(index)


def _render_table(
    table: _HtmlNode,
    *,
    builder: _TextAndStructureBuilder,
    parent_index: int | None,
) -> None:
    rows = _table_rows(table)
    captions = [
        child
        for child in table.children
        if isinstance(child, _HtmlNode) and child.tag == "caption"
    ]
    table_index = builder.begin(
        SourceRepresentationStructureType.TABLE,
        path=table.path,
        parent_index=parent_index,
        metadata={"html_tag": "table", "row_count": len(rows)},
    )
    emitted_caption = False
    for caption in captions:
        caption_text, caption_links = _inline_text_and_links(caption)
        if not caption_text.strip():
            continue
        if emitted_caption:
            builder.append(_CELL_BLOCK_SEPARATOR)
        caption_index = builder.begin(
            SourceRepresentationStructureType.PARAGRAPH,
            path=caption.path,
            parent_index=table_index,
            metadata={
                "html_tag": "caption",
                **({"links": caption_links} if caption_links else {}),
            },
        )
        builder.append(caption_text)
        builder.end(caption_index)
        emitted_caption = True
    if emitted_caption and rows:
        builder.append(_ROW_SEPARATOR)
    for row_number, row in enumerate(rows, start=1):
        cells = [
            child
            for child in row.children
            if isinstance(child, _HtmlNode) and child.tag in {"td", "th"}
        ]
        row_index = builder.begin(
            SourceRepresentationStructureType.TABLE_ROW,
            path=row.path,
            parent_index=table_index,
            metadata={
                "html_tag": "tr",
                "row_index": row_number,
                "cell_count": len(cells),
            },
        )
        logical_column = 1
        for cell_number, cell in enumerate(cells, start=1):
            colspan = _positive_int_attr(cell, "colspan", default=1)
            rowspan = _positive_int_attr(cell, "rowspan", default=1)
            cell_index = builder.begin(
                SourceRepresentationStructureType.TABLE_CELL,
                path=cell.path,
                parent_index=row_index,
                metadata={
                    "html_tag": cell.tag,
                    "row_index": row_number,
                    "cell_index": cell_number,
                    "column_index": logical_column,
                    "column_span": colspan,
                    "row_span": rowspan,
                    "header": cell.tag == "th",
                },
            )
            _render_flow_container(
                cell,
                builder=builder,
                parent_index=cell_index,
                separator=_CELL_BLOCK_SEPARATOR,
            )
            builder.end(cell_index)
            logical_column += colspan
            if cell_number < len(cells):
                builder.append(_CELL_SEPARATOR)
        builder.end(row_index)
        if row_number < len(rows):
            builder.append(_ROW_SEPARATOR)
    builder.end(table_index)


def _table_rows(table: _HtmlNode) -> list[_HtmlNode]:
    rows: list[_HtmlNode] = []
    for child in table.children:
        if not isinstance(child, _HtmlNode):
            continue
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in _TABLE_SECTION_TAGS:
            rows.extend(
                grandchild
                for grandchild in child.children
                if isinstance(grandchild, _HtmlNode) and grandchild.tag == "tr"
            )
    return rows


def _table_has_text(table: _HtmlNode) -> bool:
    for child in table.children:
        if isinstance(child, _HtmlNode) and child.tag == "caption":
            text, _links = _inline_text_and_links(child)
            if text.strip():
                return True
    rows = _table_rows(table)
    if not rows:
        return False
    for row in rows:
        for child in row.children:
            if isinstance(child, _HtmlNode) and child.tag in {"td", "th"}:
                text, _links = _inline_text_and_links(child)
                if text.strip():
                    return True
    return False


def _inline_group_text_and_links(items: list[_HtmlNode | str]) -> tuple[str, list[dict[str, object]]]:
    wrapper = _HtmlNode(tag="#flow", attrs=(), parent=None, children=list(items), path="")
    return _inline_text_and_links(wrapper)


def _inline_text_and_links(
    node: _HtmlNode,
    *,
    stop_at_blocks: bool = False,
) -> tuple[str, list[dict[str, object]]]:
    pieces: list[str] = []
    links: list[dict[str, object]] = []

    def collect(item: _HtmlNode | str, *, preserve: bool = False) -> None:
        if isinstance(item, str):
            pieces.append(_normalize_inline_data(item, preserve=preserve))
            return
        if item.tag in _EXCLUDED_TAGS or item.tag == "head":
            return
        if item.tag in _INLINE_BREAK_TAGS:
            pieces.append("\n")
            return
        if stop_at_blocks and (item.tag == "table" or _is_semantic_block(item) or _is_container(item)):
            return
        if item.tag == "a":
            local: list[str] = []
            original_pieces = pieces
            pieces_for_link = local
            # Use a small independent collector so link text can be retained
            # without coupling metadata offsets to later whitespace cleanup.
            def collect_link(child: _HtmlNode | str) -> None:
                if isinstance(child, str):
                    pieces_for_link.append(_normalize_inline_data(child, preserve=preserve))
                elif child.tag in _INLINE_BREAK_TAGS:
                    pieces_for_link.append("\n")
                elif child.tag not in _EXCLUDED_TAGS:
                    for grandchild in child.children:
                        collect_link(grandchild)

            for child in item.children:
                collect_link(child)
            link_fragment = _normalize_html_whitespace_fragment("".join(local))
            link_text = link_fragment.strip()
            if link_text:
                original_pieces.append(link_fragment)
                href = item.attr("href")
                metadata: dict[str, object] = {"text": link_text}
                if href is not None:
                    metadata["href"] = href
                title = item.attr("title")
                if title is not None:
                    metadata["title"] = title
                rel = item.attr("rel")
                if rel is not None:
                    metadata["rel"] = rel
                links.append(metadata)
            return
        child_preserve = preserve or item.tag == "pre"
        for child in item.children:
            collect(child, preserve=child_preserve)

    for child in node.children:
        collect(child, preserve=node.tag == "pre")
    return _normalize_joined_pieces(pieces, preserve=node.tag == "pre"), links



def _normalize_html_whitespace_fragment(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v\n]+", " ", normalized)
    return normalized

def _normalize_inline_data(value: str, *, preserve: bool) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if preserve:
        return normalized
    return re.sub(r"\s+", " ", normalized)


def _normalize_joined_pieces(pieces: list[str], *, preserve: bool = False) -> str:
    joined = "".join(pieces).replace("\r\n", "\n").replace("\r", "\n")
    if preserve:
        return joined.strip("\n")
    joined = re.sub(r"[ \t\f\v]+", " ", joined)
    joined = re.sub(r" *\n *", "\n", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def _heading_level(tag: str) -> int | None:
    if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
        return int(tag[1])
    return None


def _nearest_list_ancestor(node: _HtmlNode) -> _HtmlNode | None:
    current = node.parent
    while current is not None:
        if current.tag in {"ul", "ol"}:
            return current
        current = current.parent
    return None


def _list_depth(node: _HtmlNode) -> int:
    depth = 0
    current = node.parent
    while current is not None:
        if current.tag in {"ul", "ol"}:
            depth += 1
        current = current.parent
    return max(depth, 1)


def _positive_int_attr(node: _HtmlNode, name: str, *, default: int) -> int:
    raw = node.attr(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
