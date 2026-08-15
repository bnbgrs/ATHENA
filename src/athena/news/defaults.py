"""Editable starter taxonomy and international source catalogue for ATHENA News."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DefaultCategory:
    key: str
    label: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class DefaultSource:
    slug: str
    name: str
    source_class: str
    region: str
    language: str
    feed_url: str
    site_url: str
    categories: tuple[str, ...]
    perspective: str
    independence_group: str | None = None
    enabled: bool = True
    priority: int = 50
    daily_limit: int = 12


DEFAULT_CATEGORIES = (
    DefaultCategory("politics", "Politik", 1),
    DefaultCategory("geopolitics", "Geopolitik & internationale Beziehungen", 2),
    DefaultCategory("economy", "Wirtschaft & Konjunktur", 3),
    DefaultCategory("markets", "Finanzmärkte & Unternehmen", 4),
    DefaultCategory("science", "Wissenschaft & Forschung", 5),
    DefaultCategory("physics", "Physik & Grundlagenforschung", 6),
    DefaultCategory("space", "Raumfahrt & Astronomie", 7),
    DefaultCategory("ai", "KI & Machine Learning", 8),
    DefaultCategory("computing", "Computertechnik & Software", 9),
    DefaultCategory("cybersecurity", "Cybersecurity & digitale Infrastruktur", 10),
    DefaultCategory("energy", "Energie", 11),
    DefaultCategory("climate", "Klima & Umwelt", 12),
    DefaultCategory("medicine", "Medizin & Gesundheit", 13),
    DefaultCategory("biotech", "Biotechnologie & Neurowissenschaften", 14),
    DefaultCategory("defense", "Verteidigung & Militär", 15),
    DefaultCategory("society", "Gesellschaft & Demografie", 16),
    DefaultCategory("media", "Medien & Informationsökosysteme", 17),
    DefaultCategory("law", "Recht & Regulierung", 18),
    DefaultCategory("culture", "Kultur, Bildung & Ideen", 19),
    DefaultCategory("infrastructure", "Infrastruktur & Mobilität", 20),
    DefaultCategory("industry", "Rohstoffe, Industrie & Lieferketten", 21),
    DefaultCategory("emerging", "Emerging & ungewöhnliche Entwicklungen", 22),
)

# This is a starter catalogue, not a truth-ranking. Each source keeps explicit
# class/perspective metadata so the user can inspect, disable, replace, or reweight it.
DEFAULT_SOURCES = (
    DefaultSource(
        "bbc-world", "BBC News - World", "mainstream", "global", "en",
        "https://feeds.bbci.co.uk/news/world/rss.xml", "https://www.bbc.com/news/world",
        ("politics", "geopolitics", "society"), "public-service international",
        independence_group="bbc", priority=80,
    ),
    DefaultSource(
        "bbc-business", "BBC News - Business", "mainstream", "global", "en",
        "https://feeds.bbci.co.uk/news/business/rss.xml", "https://www.bbc.com/news/business",
        ("economy", "markets", "industry"), "public-service international",
        independence_group="bbc", priority=75,
    ),
    DefaultSource(
        "guardian-world", "The Guardian - World", "mainstream", "global", "en",
        "https://www.theguardian.com/world/rss", "https://www.theguardian.com/world",
        ("politics", "geopolitics", "society", "climate"), "centre-left editorial tradition",
        priority=70,
    ),
    DefaultSource(
        "aljazeera", "Al Jazeera English", "mainstream", "global-south", "en",
        "https://www.aljazeera.com/xml/rss/all.xml", "https://www.aljazeera.com/",
        ("politics", "geopolitics", "society", "economy"), "Qatar-based international",
        priority=70,
    ),
    DefaultSource(
        "dw", "Deutsche Welle", "mainstream", "europe", "en",
        "https://rss.dw.com/rdf/rss-en-all", "https://www.dw.com/en/",
        ("politics", "geopolitics", "economy", "society"), "German public international",
        priority=70,
    ),
    DefaultSource(
        "france24", "France 24 English", "mainstream", "europe", "en",
        "https://www.france24.com/en/rss", "https://www.france24.com/en/",
        ("politics", "geopolitics", "economy", "society"), "French public international",
        priority=65,
    ),
    DefaultSource(
        "npr-world", "NPR - World", "mainstream", "north-america", "en",
        "https://feeds.npr.org/1004/rss.xml", "https://www.npr.org/sections/world/",
        ("politics", "geopolitics", "society", "culture"), "US public radio",
        priority=65,
    ),
    DefaultSource(
        "nyt-world", "New York Times - World", "mainstream", "global", "en",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "https://www.nytimes.com/section/world",
        ("politics", "geopolitics", "society"), "US newspaper",
        priority=70,
    ),
    DefaultSource(
        "propublica", "ProPublica", "independent", "north-america", "en",
        "https://www.propublica.org/feeds/propublica/main", "https://www.propublica.org/",
        ("politics", "law", "society", "media"), "nonprofit investigative",
        priority=70,
    ),
    DefaultSource(
        "intercept", "The Intercept", "alternative", "north-america", "en",
        "https://theintercept.com/feed/?rss", "https://theintercept.com/",
        ("politics", "geopolitics", "defense", "media"), "independent adversarial/investigative",
        priority=50,
    ),
    DefaultSource(
        "responsible-statecraft", "Responsible Statecraft", "alternative", "north-america", "en",
        "https://responsiblestatecraft.org/feed/", "https://responsiblestatecraft.org/",
        ("geopolitics", "defense", "politics"), "restraint-oriented foreign-policy",
        priority=45,
    ),
    DefaultSource(
        "reason", "Reason", "alternative", "north-america", "en",
        "https://reason.com/feed/", "https://reason.com/",
        ("politics", "law", "society", "culture"), "libertarian",
        priority=40,
    ),
    DefaultSource(
        "nature", "Nature", "specialist", "global", "en",
        "https://www.nature.com/nature.rss", "https://www.nature.com/",
        ("science", "physics", "biotech", "medicine", "climate"), "peer-reviewed science publisher",
        priority=90,
    ),
    DefaultSource(
        "nature-physics", "Nature Physics", "specialist", "global", "en",
        "https://www.nature.com/nphys.rss", "https://www.nature.com/nphys/",
        ("physics", "science"), "peer-reviewed physics journal",
        priority=95,
    ),
    DefaultSource(
        "nasa-science", "NASA Science", "primary", "north-america", "en",
        "https://science.nasa.gov/feed/", "https://science.nasa.gov/",
        ("space", "science", "physics", "climate"), "primary government science source",
        priority=95,
    ),
    DefaultSource(
        "mit-tech-review", "MIT Technology Review", "specialist", "global", "en",
        "https://www.technologyreview.com/feed/", "https://www.technologyreview.com/",
        ("ai", "computing", "cybersecurity", "biotech", "energy"), "technology journalism",
        priority=80,
    ),
    DefaultSource(
        "ars-technica", "Ars Technica", "specialist", "global", "en",
        "https://feeds.arstechnica.com/arstechnica/index", "https://arstechnica.com/",
        ("computing", "ai", "cybersecurity", "science"), "technology journalism",
        priority=75,
    ),
    DefaultSource(
        "the-verge", "The Verge", "specialist", "global", "en",
        "https://www.theverge.com/rss/index.xml", "https://www.theverge.com/",
        ("computing", "ai", "media"), "technology/media journalism",
        priority=55,
    ),
    DefaultSource(
        "krebsonsecurity", "Krebs on Security", "independent", "global", "en",
        "https://krebsonsecurity.com/feed/", "https://krebsonsecurity.com/",
        ("cybersecurity",), "independent security reporting",
        priority=85,
    ),
    DefaultSource(
        "bleepingcomputer", "BleepingComputer", "specialist", "global", "en",
        "https://www.bleepingcomputer.com/feed/", "https://www.bleepingcomputer.com/",
        ("cybersecurity", "computing"), "security/technology reporting",
        priority=75,
    ),
    DefaultSource(
        "who-news", "World Health Organization - News", "primary", "global", "en",
        "https://www.who.int/rss-feeds/news-english.xml", "https://www.who.int/news/",
        ("medicine", "society"), "primary intergovernmental health source",
        priority=90,
    ),
    DefaultSource(
        "ecb-press", "European Central Bank", "primary", "europe", "en",
        "https://www.ecb.europa.eu/rss/press.html", "https://www.ecb.europa.eu/press/html/index.en.html",
        ("economy", "markets", "politics"), "primary central-bank source",
        priority=90,
    ),
)
