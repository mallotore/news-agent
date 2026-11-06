# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-06

First public release.

### Added
- Daily digest from RSS/Atom feeds, summarized by Claude through the `claude -p` CLI (no API key needed),
  written as a Markdown table per topic to `news/YYYY-MM-DD.md`.
- Links are copied from the feed items; the model only returns item ids, so it cannot invent URLs.
- Skips URLs already published in earlier digests (`.seen.json`, `--no-dedup` to disable).
- Per-topic `lookback_hours`, and caps per feed and per source to keep one outlet from dominating a digest.
- Retry once on transient feed and LLM failures; a failing topic does not stop the run.
- Per-topic run summary, `--dry-run` and `--check-feeds`.
- The `claude` subprocess runs with no tools, MCP servers or session persistence.
- `config.example.yaml` as a template (the personal `config.yaml` is git-ignored).
- CI (ruff, mypy, pytest with a 100% coverage gate) with a read-only token and actions pinned to commit SHAs,
  plus Dependabot for GitHub Actions and uv.
- MIT license.

[0.1.0]: https://github.com/mallotore/news-agent/releases/tag/v0.1.0
