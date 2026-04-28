from __future__ import annotations

import argparse
from pathlib import Path
import sys
from datetime import datetime

from research_lab.briefs import load_brief_json, load_brief_markdown, write_brief_json
from research_lab.engine import execute_run
from research_lab.models import ResearchBrief
from research_lab.review import compare_runs, find_previous_run_ref, load_run_snapshot, write_review_markdown


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        run_command(args)
        return
    if args.command == "brief":
        brief_command(args)
        return
    if args.command == "review":
        review_command(args)
        return

    parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-lab", description="Iterative scholarly search laboratory")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run an iterative literature search")
    run_parser.add_argument("--topic", help="Research topic to explore")
    run_parser.add_argument("--brief-file", help="Path to markdown brief file")
    run_parser.add_argument("--brief-json", help="Path to structured brief JSON")
    run_parser.add_argument("--context-file", help="Path to notes describing current progress")
    run_parser.add_argument("--context", default="", help="Inline context text")
    run_parser.add_argument("--domain", action="append", default=[], help="Domain hint, repeatable")
    run_parser.add_argument("--must-include", action="append", default=[], help="Term that should be favored")
    run_parser.add_argument("--must-exclude", action="append", default=[], help="Term that should be penalized")
    run_parser.add_argument("--since-year", type=int, help="Only search from this year onward")
    run_parser.add_argument("--iterations", type=int, default=2, help="Number of expansion rounds")
    run_parser.add_argument("--per-query", type=int, default=8, help="Candidates to fetch per query and source")
    run_parser.add_argument("--web-per-query", type=int, default=3, help="General web results to fetch per query")
    run_parser.add_argument("--full-text-top-n", type=int, default=5, help="Top candidates to enrich with full text")
    run_parser.add_argument("--llm-rerank-top-n", type=int, default=8, help="Top candidates to rerank with an optional LLM")
    run_parser.add_argument("--llm-summary-top-n", type=int, default=5, help="Top candidates to include in optional LLM synthesis")
    run_parser.add_argument("--top-k", type=int, default=20, help="Number of ranked candidates to emphasize")
    run_parser.add_argument("--program-file", default="program.md", help="Human-authored search policy file")
    run_parser.add_argument("--runs-dir", default="runs", help="Directory for run artifacts")

    brief_parser = subparsers.add_parser("brief", help="Convert a markdown brief into structured JSON")
    brief_parser.add_argument("--input", default="brief.md", help="Input markdown brief path")
    brief_parser.add_argument("--output", default="brief.json", help="Output JSON path")

    review_parser = subparsers.add_parser("review", help="Compare a run against a prior run")
    review_parser.add_argument("--run", required=True, help="Run id or run directory to review")
    review_parser.add_argument("--baseline", help="Baseline run id or run directory")
    review_parser.add_argument("--runs-dir", default="runs", help="Directory that stores run artifacts")
    review_parser.add_argument("--top-k", type=int, default=10, help="How many top candidates to compare")
    review_parser.add_argument("--output", help="Optional output markdown path")
    return parser


def run_command(args: argparse.Namespace) -> None:
    brief = _load_run_brief(args)

    program_text = _read_optional_file(args.program_file)
    if not program_text.strip():
        program_text = "# Empty program\n"

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + _slugify(brief.topic)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    db_path = runs_dir / "index.sqlite3"

    artifacts = execute_run(
        brief=brief,
        program_text=program_text,
        run_id=run_id,
        run_dir=run_dir,
        db_path=db_path,
    )

    _print_summary(artifacts.run_dir, artifacts.candidates[: brief.top_k])


def brief_command(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"missing file: {input_path}")
    brief = load_brief_markdown(input_path)
    output_path = Path(args.output)
    write_brief_json(output_path, brief)
    print(f"input: {input_path}")
    print(f"output: {output_path}")
    print(f"topic: {brief.topic}")


def review_command(args: argparse.Namespace) -> None:
    runs_dir = Path(args.runs_dir)
    current = load_run_snapshot(args.run, runs_dir)
    baseline_ref = args.baseline or find_previous_run_ref(current, runs_dir)
    if baseline_ref is None:
        raise SystemExit("no baseline run found to compare against")
    baseline = load_run_snapshot(baseline_ref, runs_dir)
    result = compare_runs(current, baseline, max(args.top_k, 1))
    output_path = Path(args.output) if args.output else current.run_dir / "review.md"
    write_review_markdown(result, output_path, max(args.top_k, 1))
    print(f"run: {current.run_id}")
    print(f"baseline: {baseline.run_id}")
    print(f"output: {output_path}")
    print(f"new_candidates: {len(result.new_candidates)}")
    print(f"dropped_candidates: {len(result.dropped_candidates)}")
    print(f"overlap: {len(result.overlap)}")


def _slugify(text: str) -> str:
    cleaned = []
    for char in text.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_"}:
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60] or "run"


def _load_run_brief(args: argparse.Namespace) -> ResearchBrief:
    if args.brief_json:
        return load_brief_json(Path(args.brief_json))
    if args.brief_file:
        return load_brief_markdown(Path(args.brief_file))

    context_text = _read_optional_file(args.context_file)
    if args.context:
        context_text = f"{context_text}\n\n{args.context}".strip()

    if not args.topic:
        raise SystemExit("either --topic, --brief-file, or --brief-json is required")

    return ResearchBrief(
        topic=args.topic,
        context=context_text,
        domains=args.domain,
        must_include=args.must_include,
        must_exclude=args.must_exclude,
        since_year=args.since_year,
        iterations=max(args.iterations, 0),
        per_query=max(args.per_query, 1),
        web_per_query=max(args.web_per_query, 0),
        full_text_top_n=max(args.full_text_top_n, 0),
        llm_rerank_top_n=max(args.llm_rerank_top_n, 0),
        llm_summary_top_n=max(args.llm_summary_top_n, 0),
        top_k=max(args.top_k, 1),
    )


def _read_optional_file(path: str | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        raise SystemExit(f"missing file: {path}")
    return file_path.read_text(encoding="utf-8")


def _print_summary(run_dir: str, candidates: list) -> None:
    print(f"run_dir: {run_dir}")
    print(f"candidates: {len(candidates)}")
    for index, candidate in enumerate(candidates[:5], start=1):
        year = candidate.year or "n/a"
        print(f"{index}. {candidate.title} [{candidate.score:.4f}] ({year}, {candidate.document_kind})")


if __name__ == "__main__":
    main(sys.argv[1:])
