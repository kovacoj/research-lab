from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from research_lab.engine import execute_run
from research_lab.models import ResearchBrief


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        run_command(args)
        return

    parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-lab", description="Iterative scholarly search laboratory")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run an iterative literature search")
    run_parser.add_argument("--topic", required=True, help="Research topic to explore")
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
    run_parser.add_argument("--top-k", type=int, default=20, help="Number of ranked candidates to emphasize")
    run_parser.add_argument("--program-file", default="program.md", help="Human-authored search policy file")
    run_parser.add_argument("--runs-dir", default="runs", help="Directory for run artifacts")
    return parser


def run_command(args: argparse.Namespace) -> None:
    context_text = _read_optional_file(args.context_file)
    if args.context:
        context_text = f"{context_text}\n\n{args.context}".strip()

    brief = ResearchBrief(
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
        top_k=max(args.top_k, 1),
    )

    program_text = _read_optional_file(args.program_file)
    if not program_text.strip():
        program_text = "# Empty program\n"

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + _slugify(args.topic)
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
