# RSS feed list — AI-centric topic ingest (ADR-0004)

Curated feeds for `topic_ingest.feeds` in `config.yaml`. Primary-source AI lab/vendor blogs plus AI-specific subfeeds from major outlets — less culture/think-piece noise at the source. The on-niche ingest gate (Issue 31) is the backstop.

| Feed URL | Rationale |
|---|---|
| `https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml` | Anthropic news/launches (community RSS mirror — Anthropic has no official feed). Primary source for Claude/Opus stories. |
| `https://blog.google/technology/ai/rss/` | Google AI blog — Gemini, on-device AI, research releases. |
| `https://openai.com/blog/rss.xml` | Primary-source OpenAI model and product announcements. |
| `https://deepmind.google/blog/rss.xml` | Google DeepMind research posts. |
| `https://huggingface.co/blog/feed.xml` | Open-source ML tooling and model releases. |
| `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` | The Verge **AI subfeed** (replaces main Verge feed). |
| `https://arstechnica.com/ai/feed/` | Ars Technica **AI section** (replaces technology-lab main feed). |

**Dropped from the pre-ADR list:** VentureBeat (enterprise think-pieces), TechCrunch (general startup noise), The Verge main feed, Ars technology-lab main feed.

## Setup notes

- Feeds are read by `src/topic_ingest/runner.py` with a 48 h recency window (configurable via `topic_ingest.recency_hours`; widens to 96 h on low on-niche yield).
- Dedup is URL hash + normalized-title similarity — the same story across feeds is collapsed to one **Topic**.
- Off-niche items are rejected by the ingest niche gate before persisting (`topic_ingest.niche_gate`).
- Hacker News front-page corroboration boosts ranking during scripter Stage A (`topic_ingest.hn`).
- Add or remove feeds in `config.yaml` only; no code change required. Prefer stable RSS/Atom endpoints with English content.
