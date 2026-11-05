# news-agent

Daily news digest from **official feeds**, summarized by Claude into a Markdown table
(headline, context, why it's interesting, official link). Runs locally, on demand.

It calls the **Claude Code CLI** (`claude -p`), so it uses your Claude subscription (e.g. Pro).
No API key and no API credits are needed.

## How it works

1. Reads the RSS/Atom feeds you configure per topic.
2. Keeps items from the last N hours, de-duplicated.
3. Asks Claude (one call per topic, no tools, no session) to pick the best ones and write the context / "why it's interesting".
4. Links are copied from the feed items. The model only returns item ids, so it cannot invent a URL.
5. Writes `news/YYYY-MM-DD.md`.

## Setup

1. Install [Claude Code](https://code.claude.com) and run `claude` once to log in with your account.
2. Install [uv](https://docs.astral.sh/uv/) (it downloads the right Python for you).

```bash
uv lock --upgrade                           # once: resolve and pin the latest stable versions
uv run news-agent --check-feeds   # validate feed URLs first
uv run news-agent                 # all topics, config defaults
```

> `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` are removed from the environment of the `claude`
> subprocess on purpose: if they were set, Claude Code would bill the API instead of your subscription.

## Options

```bash
-t ai,java          # only some topics
-l en               # output language (overrides the config)
-m sonnet           # model alias or name (overrides the config; default: haiku)
--hours 24          # look-back window (overrides the config, including per-topic values)
-o today.md         # custom output file
--no-dedup          # don't skip URLs from previous digests (and don't update the state)
--dry-run           # list candidates, no LLM call, no file
--check-feeds       # test every feed URL and exit
```

Already-published URLs are remembered in `<output_dir>/.seen.json` (git-ignored, pruned after the look-back
window) so the same story doesn't reappear in consecutive digests. Delete the file or use `--no-dedup` to reset.

Add a topic or a source by editing `config.yaml` (a topic is just a title plus a list of feed URLs).
A quiet topic can have its own window with `lookback_hours: 240` inside the topic; otherwise the global value applies.

To keep one outlet from dominating a topic, `max_items_per_feed` caps candidates per feed and
`max_items_per_source` (default 3) caps entries per source in the final digest. The prompt also asks the model
to prefer the original source over secondary coverage of the same story.

## Choosing a model

The task is selecting and rephrasing short excerpts that are already in the prompt, so a small model is enough.
Start with `haiku`; switch to `sonnet` if the "why it's interesting" column feels shallow.
Usage counts against your subscription limits.

## Docker?

Not provided: the container would need the `claude` CLI and your login credentials inside it,
which is more fragile than running `uv run` locally.

## Tests

```bash
uv run pytest             # tests
uv run ruff check .       # lint
uv run ruff format .      # format
uv run mypy               # type check
```

## Layout

```
src/news_agent/   application code (cli, config, feeds, llm, summarize, render, models)
tests/            pytest suite
config.yaml       topics and feed URLs
```
