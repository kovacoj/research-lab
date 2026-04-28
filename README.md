# research_lab

`research_lab` is a small literature-search laboratory for autonomous research runs.

It takes a topic and your current notes, searches scholarly indexes plus the open web, deduplicates papers, reranks them, expands from the strongest matches, reads accessible full text when possible, and writes a reproducible run folder.

## Design

The repo follows the same separation of concerns as `autoresearch`, but for literature search instead of model training:

- Fixed code: retrieval, ranking, iteration, storage, reporting.
- Human-authored instructions: `program.md`.
- Mutable run outputs: `runs/<timestamp>-<slug>/`.

The agent does not self-edit code during a run. It only produces search artifacts.

## Supported sources

- OpenAlex
- Semantic Scholar
- DuckDuckGo HTML search for broad web fallback

The lab still prefers structured scholarly metadata first, but it can now fall back to broader web search and read supporting web pages or PDFs for evidence.

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
  --web-per-query 3
```

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
- `SEMANTIC_SCHOLAR_API_KEY`: optional Semantic Scholar API key.
- `RESEARCH_LAB_LLM_MODEL`: optional model name for the LLM reranker/summarizer.
- `RESEARCH_LAB_LLM_BASE_URL`: optional OpenAI-compatible base URL. Defaults to `https://api.openai.com/v1`.
- `RESEARCH_LAB_LLM_API_KEY`: optional API key for the configured LLM endpoint.

The code works without keys, but public endpoints may rate limit more aggressively.

If `pdftotext` is installed on your machine, PDF extraction is significantly better. Without it, the lab falls back to a best-effort plain-text extraction path.

## Useful command

```bash
research-lab run \
  --topic "graph neural networks for molecular property prediction" \
  --context-file notes.md \
  --iterations 2 \
  --per-query 8 \
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
- evidence snippets in the final report for argument strengthening

If you set `RESEARCH_LAB_LLM_MODEL`, the lab will also:

- rerank the strongest heuristic candidates with an OpenAI-compatible chat completion API
- add short model-generated reasons to each candidate
- produce an `LLM Synthesis` section that helps strengthen your argument and suggests follow-up queries

If the LLM call fails or is not configured, the run still completes with heuristic ranking only.
