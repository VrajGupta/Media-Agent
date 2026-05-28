"""Issue 30 — curated AI-focused feed list."""

from pathlib import Path

import feedparser

from src.config_loader.loader import load_config

CURATED_FEEDS = [
    "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
    "https://blog.google/technology/ai/rss/",
    "https://openai.com/blog/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/ai/feed/",
]

DROPPED_NOISE_MARKERS = (
    "venturebeat.com",
    "theverge.com/rss/index.xml",
    "techcrunch.com",
    "feeds.arstechnica.com/arstechnica/technology-lab",
)


def test_config_yaml_has_curated_ai_feeds():
    cfg = load_config(Path("config.yaml"))
    assert cfg.topic_ingest.feeds == CURATED_FEEDS


def test_curated_feeds_exclude_culture_noise_sources():
    joined = " ".join(CURATED_FEEDS).lower()
    for marker in DROPPED_NOISE_MARKERS:
        assert marker not in joined


def test_curated_feed_urls_parse():
    for url in CURATED_FEEDS:
        parsed = feedparser.parse(url)
        assert len(getattr(parsed, "entries", []) or []) > 0, url
