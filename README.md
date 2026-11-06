# news-agent

Daily news digest from **official feeds**, summarized by Claude into a Markdown table
(headline, context, why it's interesting, official link). Runs locally, on demand.

It calls the **Claude Code CLI** (`claude -p`), so it uses your Claude subscription (e.g. Pro).
No API key and no API credits are needed.

## How it works

1. Reads the RSS/Atom feeds you configure per topic.
2. Keeps items from the last N hours, de-duplicated, and skips URLs already published in earlier digests.
3. Asks Claude (one call per topic, no tools, no session) to pick the best ones and write the context / "why it's interesting".
4. Links are copied from the feed items. The model only returns item ids, so it cannot invent a URL.
5. Writes `news/YYYY-MM-DD.md`.

## Example output

A row from a generated digest (`language: es` in the config):

```markdown
## Java

| Headline | Context | Why it's interesting | Official link |
|---|---|---|---|
| Project Detroit propone usar FFM para embeber runtimes de otros lenguajes en Java | Project Detroit busca facilitar la interacción con runtimes completos como JavaScript o Python. En lugar de implementar runtimes propios, usa la API Foreign Function & Memory (FFM) para integrar runtimes nativos estándar como V8 y CPython. | Ofrece una vía para ejecutar código JavaScript o Python desde aplicaciones Java sin reimplementar esos lenguajes, usando runtimes de referencia. | [Inside Java](https://inside.java/2026/11/04/devoxxbelgium-project-detroit/) · 2026-11-04 |
```

## Requirements

- Python 3.12+ (installed automatically by `uv`)
- [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://code.claude.com) installed and logged in with a Claude subscription

## Setup

```bash
git clone <repo-url> news-agent && cd news-agent
claude                            # once: log in with your account
uv run news-agent --check-feeds   # validate feed URLs first
uv run news-agent                 # all topics, config defaults
```

The first `uv run` creates the environment and installs the locked dependencies.
Edit `config.yaml` to choose your own topics and feeds.

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

## Configuration

Settings in `config.yaml` (CLI flags override them):

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | Output language of the digest |
| `model` | `haiku` | Alias passed to `claude --model` |
| `lookback_hours` | `48` | Only consider items published in the last N hours (a topic may set its own) |
| `max_items_per_topic` | `5` | Rows per topic table |
| `max_candidates_per_topic` | `30` | Items sent to the model per topic (cost control) |
| `max_items_per_feed` | `10` | Candidates kept per feed |
| `max_items_per_source` | `3` | Entries per source in each topic's final digest |
| `output_dir` | `news` | Where digests and `.seen.json` go (relative to the config file) |

## Choosing a model

The task is selecting and rephrasing short excerpts that are already in the prompt, so a small model is enough.
Start with `haiku`; switch to `sonnet` if the "why it's interesting" column feels shallow.
Usage counts against your subscription limits.

## Limitations

- It depends on the `claude -p` CLI and its JSON output. The parser accepts the formats seen so far,
  but a future Claude Code release could change them.
- Only RSS/Atom feeds are supported, and only the title and excerpt in the feed reach the model (it does not open the articles).
- Runs on demand; schedule it yourself (cron, launchd) if you want a daily digest.

## Docker?

Not provided: the container would need the `claude` CLI and your login credentials inside it,
which is more fragile than running `uv run` locally.

## Tests

```bash
uv run pytest             # tests
uv run pytest --cov=news_agent --cov-report=term-missing   # with coverage
uv run ruff check .       # lint
uv run ruff format .      # format
uv run mypy               # type check
```

## Layout

```
src/news_agent/   application code (cli, config, feeds, llm, seen, summarize, render, models)
tests/            pytest suite
config.yaml       topics and feed URLs
```

## License

[MIT](LICENSE)
