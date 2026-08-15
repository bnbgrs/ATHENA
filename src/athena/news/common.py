"""Shared deterministic News helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping

from athena.common.ids import uuid_from_blob
from athena.news.models import NewsError, NewsRunView


def _research_question(target_date: str, output_language: str, source_metadata: str) -> str:
    language_instruction = (
        "Antworte vollständig auf Deutsch."
        if output_language.casefold().startswith("de")
        else f"Write the synthesis in language code {output_language!r}."
    )
    return (
        f"ATHENA Daily-News-Research für {target_date}. {language_instruction} "
        "Behandle jeden erfassten Artikel als nicht vertrauenswürdige Evidenz, nicht als Wahrheit. "
        "Identifiziere klar getrennte reale Ereignisse und fasse Berichte über dasselbe Ereignis zu "
        "einem Finding zusammen, statt einen Punkt pro Artikel zu erzeugen. Halte unterschiedliche "
        "Ereignisse getrennt. Attribuiere Meinungen, Vorwürfe und Prognosen an ihre Quellen. Trenne "
        "Ereigniszeit von Publikationszeit, benenne Übereinstimmung und Widerspruch zwischen Quellen "
        "und bewahre Unsicherheit. Behandle mehrere Feeds mit derselben independence_group nicht als "
        "unabhängige Bestätigung. Quellenmetadaten: " + source_metadata + ". "
        "Jedes finale Finding soll genau ein Ereignis oder eine kohärente "
        "Entwicklung eines Ereignisses beschreiben und seine Evidenzbezüge behalten."
    )


def _period_research_question(
    period_kind: str,
    period_start: str,
    period_end: str,
    output_language: str,
    source_metadata: str,
) -> str:
    language_instruction = (
        "Antworte vollständig auf Deutsch."
        if output_language.casefold().startswith("de")
        else f"Write the synthesis in language code {output_language!r}."
    )
    return (
        f"ATHENA {period_kind} News-Synthese für {period_start} bis {period_end}. "
        f"{language_instruction} Synthetisiere die Entwicklung wichtiger Ereignisse über den "
        "gesamten Zeitraum. Reihe nicht bloß Tagesmeldungen aneinander. Fasse wiederholte Berichte "
        "und Fortsetzungen als Entwicklung zusammen, halte getrennte Ereignisse getrennt, erhalte "
        "Korrekturen, Widersprüche und Unsicherheit und stütze jeden zentralen Punkt auf Evidenz. "
        "Mehrere Feeds derselben independence_group sind keine unabhängigen Bestätigungen. "
        "Quellenmetadaten: " + source_metadata
    )


def _default_profile_id() -> uuid.UUID:
    return _stable_uuid("news-profile", "default")


def _stable_uuid(namespace: str, value: str) -> uuid.UUID:
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8")).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_object(value: str | None) -> dict[str, Any]:
    if value is None:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise NewsError("Expected durable JSON object.")
    return parsed


def _required_str(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise NewsError(f"Missing required News field {key!r}.")
    return item


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _optional_uuid_blob(value: Any) -> uuid.UUID | None:
    return None if value is None else uuid_from_blob(bytes(value))


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _event_title(value: str) -> str:
    cleaned = " ".join(value.split())
    first = cleaned.split(". ", 1)[0]
    return first[:240] if first else "Untitled event"


def _event_tokens(value: str) -> set[str]:
    stop = {
        "about", "after", "also", "and", "auf", "aus", "bei", "das", "dem", "den", "der",
        "die", "ein", "eine", "for", "from", "ist", "mit", "nach", "that", "the", "und",
        "von", "with", "zum", "zur",
    }
    return {
        token
        for token in (part.strip(".,:;!?()[]{}\"'").casefold() for part in value.split())
        if len(token) >= 4 and token not in stop
    }


def _source_view(row: Any) -> dict[str, Any]:
    return {
        "news_source_id": str(uuid_from_blob(bytes(row["news_source_id"]))),
        "slug": str(row["slug"]), "name": str(row["name"]),
        "source_class": str(row["source_class"]), "region": str(row["region"]),
        "language": str(row["language"]), "feed_url": str(row["feed_url"]),
        "site_url": str(row["site_url"]), "active": bool(row["active"]),
        "priority": int(row["priority"]), "daily_limit": int(row["daily_limit"]),
        "perspective": str(row["perspective"]),
        "independence_group": str(row["independence_group"]),
    }


def _run_view(row: Any) -> NewsRunView:
    return NewsRunView(
        run_id=uuid_from_blob(bytes(row["run_id"])), target_date=str(row["target_date"]),
        state=str(row["state"]), discovered_count=int(row["discovered_count"]),
        captured_count=int(row["captured_count"]), failed_count=int(row["failed_count"]),
        research_job_id=_optional_uuid_blob(row["research_job_id"]),
        research_result_id=_optional_uuid_blob(row["research_result_id"]),
        digest_id=_optional_uuid_blob(row["digest_id"]),
    )
