# research_lab

`research_lab` is an agent-first literature-search laboratory.

The intended interface is an OpenCode agent working inside this repo. You give the agent a topic, your current notes, and the kind of help you need. The agent can then search scholarly indexes plus the open web, rerank results, expand from promising leads, read accessible full text, and leave behind reproducible artifacts in `runs/`.

The Python code in this repo is not the product surface. It is a toolkit the agent can use when it is useful.

## Design

The repo follows the same separation of concerns as `autoresearch`, but for literature search instead of model training:

- Fixed code: retrieval, ranking, iteration, storage, reporting.
- Human-authored instructions: `program.md`.
- Mutable run outputs: `runs/<timestamp>-<slug>/`.

The agent does not self-edit code during a run. It only produces search artifacts.

## Supported sources

- arXiv
- OpenAlex
- Semantic Scholar
- Google Scholar scraping as an experimental opt-in source
- DuckDuckGo HTML search for broad web fallback

The lab still prefers structured scholarly metadata first, but it can now fall back to broader web search and read supporting web pages or PDFs for evidence.

## Agent-First Workflow

The normal way to use this repo is:

```bash
cd /home/cady/personal/research_lab
opencode
```

Then give the agent a task like:

```text
Read program.md and brief.md.example. Help me create a brief for my current research question, then run a search and summarize the strongest supporting sources.
```

Or if you already have notes:

```text
Use my notes below to prepare brief.md, search for relevant papers and supporting articles, and write a report that helps strengthen my argument.
```

The agent may choose to use the Python tools in this repo, or it may work more directly with the artifacts and prompts. The repo is designed to support both.

## Python Tools

The Python CLI remains available as optional tooling for the agent or for you directly.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

research-lab run \
  --topic "test-time adaptation for large language models" \
  --context-file notes.md \
  --full-text-top-n 5
```

Or without installing the script entrypoint:

```bash
PYTHONPATH=src python3 -m research_lab run \
  --topic "test-time adaptation for large language models" \
  --context-file notes.md \
  --scholar-per-query 2 \
  --web-per-query 3
```

## Brief Workflow

For terminal use, one clean loop is:

1. Write `brief.md`
2. Convert it to structured JSON
3. Run the search from that brief

```bash
PYTHONPATH=src python3 -m research_lab brief --input brief.md --output brief.json
PYTHONPATH=src python3 -m research_lab run --brief-json brief.json
```

You can also skip the intermediate JSON file:

```bash
PYTHONPATH=src python3 -m research_lab run --brief-file brief.md
```

The markdown parser understands sections like `Topic`, `Context`, `Domains`, `Must Include`, `Must Exclude`, and the numeric knobs such as `Iterations` or `Top K`.

Start from `brief.md.example` if you want a parser-friendly template.

## Review Workflow

To compare a new run against a previous one:

```bash
PYTHONPATH=src python3 -m research_lab review --run runs/<current-run-id>
```

This writes `review.md` into the run directory. If you want to choose the baseline explicitly:

```bash
PYTHONPATH=src python3 -m research_lab review \
  --run runs/<current-run-id> \
  --baseline runs/<older-run-id>
```

If `--baseline` is omitted, the tool tries to find the most recent earlier run for the same topic from `runs/index.sqlite3`.

## Outputs

Each run writes a folder like:

```text
runs/20260428-123456-test-time-adaptation-for-large-language-models/
  brief.json
  queries.json
  candidates.json
  report.md
  references.bib
```

The root `runs/index.sqlite3` file keeps a searchable run history.

## Environment variables

- `OPENALEX_API_KEY`: optional OpenAlex API key.
- `OPENALEX_EMAIL`: optional email sent as `mailto` for polite pool usage.
- `SEMANTIC_SCHOLAR_API_KEY`: Semantic Scholar API key. The lab only uses Semantic Scholar when this is configured, to avoid unreliable public-endpoint rate limiting.
- `RESEARCH_LAB_LLM_MODEL`: optional model name for the LLM reranker/summarizer.
- `RESEARCH_LAB_LLM_BASE_URL`: optional OpenAI-compatible base URL. Defaults to `https://api.openai.com/v1`.
- `RESEARCH_LAB_LLM_API_KEY`: optional API key for the configured LLM endpoint.

The code works without keys, but Semantic Scholar retrieval is skipped unless `SEMANTIC_SCHOLAR_API_KEY` is configured.

Google Scholar retrieval is intentionally opt-in through `--scholar-per-query`. It uses brittle HTML scraping rather than an official API, so it may fail or get blocked on some runs.

If `pdftotext` is installed on your machine, PDF extraction is significantly better. Without it, the lab falls back to a best-effort plain-text extraction path.

## Useful command

```bash
research-lab run \
  --topic "graph neural networks for molecular property prediction" \
  --context-file notes.md \
  --iterations 2 \
  --per-query 8 \
  --scholar-per-query 2 \
  --web-per-query 3 \
  --full-text-top-n 5 \
  --llm-rerank-top-n 8 \
  --llm-summary-top-n 5 \
  --top-k 20
```

## Current scope

This version is built for robustness first:

- retries and partial-failure handling for network calls
- scholarly search plus general web fallback
- heuristic reranking that weighs title alignment more strongly
- accessible full-text and PDF extraction when possible
- explicit tracking of abstract-only or paywalled papers that may need user retrieval
- evidence snippets in the final report for argument strengthening

If you set `RESEARCH_LAB_LLM_MODEL`, the lab will also:

- rerank the strongest heuristic candidates with an OpenAI-compatible chat completion API
- add short model-generated reasons to each candidate
- produce an `LLM Synthesis` section that helps strengthen your argument and suggests follow-up queries

If the LLM call fails or is not configured, the run still completes with heuristic ranking only.

## OpenCode Prompts

If you run OpenCode inside this repo, there are prompt files under `.opencode/agents/` for:

- orchestrating the whole lab run
- preparing `brief.md`
- reviewing a run against a previous run
- drilling into evidence for a specific claim or argument
