# RSS feed list — Tech/AI topic ingest

Curated feeds for `topic_ingest.feeds` in `config.yaml`. Mixed consumer news + research/lab blogs so the scripter gets both headline stories and deeper technical angles.

| Feed URL | Rationale |
|---|---|
| `https://feeds.arstechnica.com/arstechnica/technology-lab` | Deep technical reporting; strong for hardware, policy, and science angles. |
| `https://techcrunch.com/feed/` | Startup/funding and product-launch velocity; good hook material. |
| `https://www.theverge.com/rss/index.xml` | Consumer tech + AI product news; broad mainstream reach. |
| `https://openai.com/blog/rss.xml` | Primary-source AI model and product announcements. |
| `https://deepmind.google/blog/rss.xml` | Research-heavy Google DeepMind posts; complements OpenAI. |
| `https://huggingface.co/blog/feed.xml` | Open-source ML tooling and model releases; niche but on-topic. |
| `https://venturebeat.com/feed/` | Enterprise AI and industry analysis; useful for stat-heavy hooks. |

## Setup notes

- Feeds are read by `src/topic_ingest/runner.py` with a 48 h recency window (configurable via `topic_ingest.recency_hours`).
- Dedup is URL hash + normalized-title similarity — the same story across Verge/TechCrunch/Ars is collapsed to one **Topic**.
- Add or remove feeds in `config.yaml`; no code change required. Prefer feeds with stable RSS/Atom endpoints and English content.
