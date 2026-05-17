from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

from research_lab.briefs import load_brief_markdown
from research_lab.engine import execute_run
from research_lab.models import ResearchBrief, RunArtifacts
from research_lab.review import compare_runs, write_review_markdown
from research_lab.run_history import find_previous_run_ref, load_run_snapshot

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "research-lab"
SERVER_VERSION = "0.1.0"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="research-lab-mcp", description="Local MCP server for research-lab")
    parser.add_argument("--workspace", required=True, help="Workspace root where research artifacts will be written")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    if not workspace.exists() or not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    server = ResearchLabMcpServer(workspace)
    run_stdio_server(server)


@dataclass(slots=True)
class WorkspacePaths:
    workspace: Path

    def __post_init__(self) -> None:
        self.workspace = self.workspace.resolve()

    @property
    def research_dir(self) -> Path:
        return self.workspace / "research"

    @property
    def default_runs_dir(self) -> Path:
        return self.research_dir / "runs"

    def resolve_workspace_path(self, path_text: str, *, must_exist: bool) -> Path:
        if not path_text:
            raise ValueError("path is required")
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        _ensure_within(resolved, self.workspace, "workspace")
        if must_exist and not resolved.exists():
            raise ValueError(f"path not found: {resolved}")
        return resolved

    def resolve_research_path(self, path_text: str, *, must_exist: bool) -> Path:
        resolved = self.resolve_workspace_path(path_text, must_exist=must_exist)
        _ensure_within(resolved, self.research_dir, "workspace research directory")
        return resolved

    def relative_to_workspace(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.workspace))


class ResearchLabMcpServer:
    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths(workspace)
        self.program_text = _read_default_program_text()

    def handle_request(self, method: str, params: dict | None = None) -> dict:
        payload = params or {}
        if method == "initialize":
            return {
                "protocolVersion": payload.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": _tool_definitions()}
        if method == "tools/call":
            return self._call_tool(payload)
        raise ValueError(f"unsupported method: {method}")

    def _call_tool(self, payload: dict) -> dict:
        name = str(payload.get("name", "")).strip()
        arguments = payload.get("arguments") or {}
        try:
            if name == "research_lab_run_search":
                result = self.run_search(arguments)
            elif name == "research_lab_run_from_brief":
                result = self.run_from_brief(arguments)
            elif name == "research_lab_create_brief":
                result = self.create_brief(arguments)
            elif name == "research_lab_list_runs":
                result = self.list_runs(arguments)
            elif name == "research_lab_read_report":
                result = self.read_report(arguments)
            elif name == "research_lab_review_run":
                result = self.review_run(arguments)
            else:
                raise ValueError(f"unknown tool: {name}")
        except ValueError as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(exc)}],
            }

        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=True)}],
            "structuredContent": result,
        }

    def run_search(self, arguments: dict) -> dict:
        brief = _brief_from_payload(arguments)
        runs_dir = self._resolve_runs_dir(arguments.get("output_dir"))
        artifacts = self._execute_run(brief, runs_dir)
        return _run_result(self.paths, artifacts)

    def run_from_brief(self, arguments: dict) -> dict:
        brief_path = self.paths.resolve_workspace_path(str(arguments.get("brief_path", "")), must_exist=True)
        if not brief_path.is_file():
            raise ValueError(f"brief file not found: {brief_path}")
        brief = load_brief_markdown(brief_path)
        runs_dir = self._resolve_runs_dir(arguments.get("output_dir"))
        artifacts = self._execute_run(brief, runs_dir)
        result = _run_result(self.paths, artifacts)
        result["brief_path"] = self.paths.relative_to_workspace(brief_path)
        return result

    def list_runs(self, arguments: dict) -> dict:
        runs_dir = self._resolve_runs_dir(arguments.get("output_dir"), must_exist=False)
        limit = max(_parse_int(arguments.get("limit")) or 20, 1)
        if not runs_dir.exists():
            return {"status": "ok", "runs_dir": self.paths.relative_to_workspace(runs_dir), "runs": []}

        runs = []
        for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True)[:limit]:
            brief_path = run_dir / "brief.json"
            topic = ""
            if brief_path.exists():
                topic = ResearchBrief.from_dict(json.loads(brief_path.read_text(encoding="utf-8"))).topic
            report_path = run_dir / "report.md"
            runs.append(
                {
                    "run_id": run_dir.name,
                    "run_dir": self.paths.relative_to_workspace(run_dir),
                    "topic": topic,
                    "report_path": self.paths.relative_to_workspace(report_path) if report_path.exists() else "",
                }
            )
        return {"status": "ok", "runs_dir": self.paths.relative_to_workspace(runs_dir), "runs": runs}

    def create_brief(self, arguments: dict) -> dict:
        brief = _brief_from_payload(arguments)
        output_path = self.paths.resolve_research_path(str(arguments.get("output_path", "")), must_exist=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_brief_markdown(brief), encoding="utf-8")
        return {
            "status": "ok",
            "output_path": self.paths.relative_to_workspace(output_path),
            "topic": brief.topic,
        }

    def read_report(self, arguments: dict) -> dict:
        runs_dir = self._resolve_runs_dir(arguments.get("output_dir"), must_exist=False)
        run_dir = self._resolve_run_dir(arguments.get("run"), runs_dir)
        report_path = run_dir / "report.md"
        if not report_path.exists():
            raise ValueError(f"missing artifact: {self.paths.relative_to_workspace(report_path)}")
        return {
            "status": "ok",
            "run_id": run_dir.name,
            "report_path": self.paths.relative_to_workspace(report_path),
            "content": report_path.read_text(encoding="utf-8"),
        }

    def review_run(self, arguments: dict) -> dict:
        runs_dir = self._resolve_runs_dir(arguments.get("output_dir"), must_exist=False)
        run_ref = arguments.get("run")
        if run_ref is None or not str(run_ref).strip():
            raise ValueError("run is required")

        current = load_run_snapshot(str(self._resolve_run_dir(run_ref, runs_dir)), runs_dir)
        baseline_ref = arguments.get("baseline")
        if baseline_ref is None or not str(baseline_ref).strip():
            baseline_ref = find_previous_run_ref(current, runs_dir)
        if baseline_ref is None:
            raise ValueError("no baseline run found to compare against")

        baseline = load_run_snapshot(str(self._resolve_run_dir(baseline_ref, runs_dir)), runs_dir)
        top_k = max(_parse_int(arguments.get("top_k")) or 10, 1)
        result = compare_runs(current, baseline, top_k)
        output_path = self._resolve_review_output_path(arguments.get("output_path"), current.run_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_review_markdown(result, output_path, top_k)
        return {
            "status": "ok",
            "run_id": current.run_id,
            "baseline_run_id": baseline.run_id,
            "output_path": self.paths.relative_to_workspace(output_path),
            "new_candidates": len(result.new_candidates),
            "dropped_candidates": len(result.dropped_candidates),
            "overlap": len(result.overlap),
        }

    def _execute_run(self, brief: ResearchBrief, runs_dir: Path) -> RunArtifacts:
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + _slugify(brief.topic)
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return execute_run(
            brief=brief,
            program_text=self.program_text,
            run_id=run_id,
            run_dir=run_dir,
            db_path=runs_dir / "index.sqlite3",
        )

    def _resolve_runs_dir(self, output_dir: object, *, must_exist: bool = False) -> Path:
        path_text = str(output_dir).strip() if output_dir is not None else "research/runs"
        if not path_text:
            path_text = "research/runs"
        return self.paths.resolve_research_path(path_text, must_exist=must_exist)

    def _resolve_run_dir(self, run_ref: object, runs_dir: Path) -> Path:
        if run_ref is None or not str(run_ref).strip():
            if not runs_dir.exists():
                raise ValueError(f"runs directory not found: {self.paths.relative_to_workspace(runs_dir)}")
            run_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
            if not run_dirs:
                raise ValueError("no runs found")
            return run_dirs[-1]

        run_text = str(run_ref).strip()
        run_path = Path(run_text)
        if run_path.is_absolute() or len(run_path.parts) > 1:
            resolved = self.paths.resolve_research_path(run_text, must_exist=True)
        else:
            resolved = (runs_dir / run_text).resolve(strict=True)
            _ensure_within(resolved, self.paths.research_dir, "workspace research directory")
        if not resolved.is_dir():
            raise ValueError(f"run not found: {run_text}")
        return resolved

    def _resolve_review_output_path(self, output_path: object, current_run_dir: Path) -> Path:
        if output_path is None or not str(output_path).strip():
            return current_run_dir / "review.md"
        return self.paths.resolve_research_path(str(output_path), must_exist=False)


def run_stdio_server(server: ResearchLabMcpServer) -> None:
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    mode: str | None = None
    while True:
        result = _read_message(reader)
        if result is None:
            return
        message, observed_mode = result
        if mode is None:
            mode = observed_mode

        request_id = message.get("id")
        method = message.get("method")
        if not method:
            if request_id is not None:
                _write_message(writer, _jsonrpc_error(request_id, -32600, "missing method"), mode)
            continue

        if request_id is None:
            if method == "notifications/initialized":
                continue
            continue

        try:
            result = server.handle_request(method, message.get("params"))
        except ValueError as exc:
            _write_message(writer, _jsonrpc_error(request_id, -32602, str(exc)), mode)
            continue
        except Exception as exc:  # pragma: no cover - defensive wrapper for MCP clients
            _write_message(writer, _jsonrpc_error(request_id, -32000, str(exc)), mode)
            continue

        _write_message(writer, {"jsonrpc": "2.0", "id": request_id, "result": result}, mode)


def _tool_definitions() -> list[dict]:
    brief_properties = {
        "topic": {"type": "string", "description": "Research topic to explore"},
        "context": {"type": "string", "description": "Caller-provided research context", "default": ""},
        "domains": {"type": "array", "items": {"type": "string"}, "default": []},
        "must_include": {"type": "array", "items": {"type": "string"}, "default": []},
        "must_exclude": {"type": "array", "items": {"type": "string"}, "default": []},
        "since_year": {"type": "integer"},
        "iterations": {"type": "integer", "default": 2},
        "per_query": {"type": "integer", "default": 8},
        "web_per_query": {"type": "integer", "default": 3},
        "scholar_per_query": {"type": "integer", "default": 0},
        "full_text_top_n": {"type": "integer", "default": 5},
        "llm_rerank_top_n": {"type": "integer", "default": 8},
        "llm_summary_top_n": {"type": "integer", "default": 5},
        "top_k": {"type": "integer", "default": 20},
        "output_dir": {"type": "string", "default": "research/runs"},
    }
    return [
        {
            "name": "research_lab_run_search",
            "description": "Run a literature search from structured topic and context input.",
            "inputSchema": {"type": "object", "properties": brief_properties, "required": ["topic"]},
        },
        {
            "name": "research_lab_run_from_brief",
            "description": "Run the existing brief workflow from a Markdown brief inside the caller workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "brief_path": {"type": "string"},
                    "output_dir": {"type": "string", "default": "research/runs"},
                },
                "required": ["brief_path"],
            },
        },
        {
            "name": "research_lab_create_brief",
            "description": "Create a parser-friendly Markdown brief inside the caller workspace research directory.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "context": {"type": "string", "default": ""},
                    "domains": {"type": "array", "items": {"type": "string"}, "default": []},
                    "must_include": {"type": "array", "items": {"type": "string"}, "default": []},
                    "must_exclude": {"type": "array", "items": {"type": "string"}, "default": []},
                    "since_year": {"type": "integer"},
                    "iterations": {"type": "integer", "default": 2},
                    "per_query": {"type": "integer", "default": 8},
                    "web_per_query": {"type": "integer", "default": 3},
                    "scholar_per_query": {"type": "integer", "default": 0},
                    "full_text_top_n": {"type": "integer", "default": 5},
                    "llm_rerank_top_n": {"type": "integer", "default": 8},
                    "llm_summary_top_n": {"type": "integer", "default": 5},
                    "top_k": {"type": "integer", "default": 20},
                    "output_path": {"type": "string"},
                },
                "required": ["topic", "output_path"],
            },
        },
        {
            "name": "research_lab_list_runs",
            "description": "List known research runs under the configured workspace output directory.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_dir": {"type": "string", "default": "research/runs"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "research_lab_read_report",
            "description": "Read a generated report from a specific run or the latest run.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run": {"type": "string"},
                    "output_dir": {"type": "string", "default": "research/runs"},
                },
            },
        },
        {
            "name": "research_lab_review_run",
            "description": "Compare a run against a baseline and write a review markdown file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run": {"type": "string"},
                    "baseline": {"type": "string"},
                    "output_dir": {"type": "string", "default": "research/runs"},
                    "top_k": {"type": "integer", "default": 10},
                    "output_path": {"type": "string"},
                },
                "required": ["run"],
            },
        },
    ]


def _brief_from_payload(payload: dict) -> ResearchBrief:
    brief = ResearchBrief.from_dict(
        {
            "topic": payload.get("topic", ""),
            "context": payload.get("context", ""),
            "domains": payload.get("domains", []),
            "must_include": payload.get("must_include", []),
            "must_exclude": payload.get("must_exclude", []),
            "since_year": payload.get("since_year"),
            "iterations": payload.get("iterations"),
            "per_query": payload.get("per_query"),
            "web_per_query": payload.get("web_per_query"),
            "scholar_per_query": payload.get("scholar_per_query"),
            "full_text_top_n": payload.get("full_text_top_n"),
            "llm_rerank_top_n": payload.get("llm_rerank_top_n"),
            "llm_summary_top_n": payload.get("llm_summary_top_n"),
            "top_k": payload.get("top_k"),
        }
    )
    if not brief.topic.strip():
        raise ValueError("topic is required")
    return brief


def _run_result(paths: WorkspacePaths, artifacts: RunArtifacts) -> dict:
    run_dir = Path(artifacts.run_dir)
    return {
        "status": "ok",
        "run_id": artifacts.run_id,
        "run_dir": paths.relative_to_workspace(run_dir),
        "report_path": paths.relative_to_workspace(run_dir / "report.md"),
        "references_path": paths.relative_to_workspace(run_dir / "references.bib"),
        "top_sources": [
            {
                "title": candidate.title,
                "year": candidate.year,
                "score": candidate.score,
                "url": candidate.url or candidate.open_access_url,
            }
            for candidate in artifacts.candidates[:5]
        ],
    }


def _brief_markdown(brief: ResearchBrief) -> str:
    sections = [
        ("# Topic", brief.topic),
        ("## Context", brief.context.strip() or "(none)"),
        ("## Domains", _list_block(brief.domains)),
        ("## Must Include", _list_block(brief.must_include)),
        ("## Must Exclude", _list_block(brief.must_exclude)),
        ("## Since Year", "" if brief.since_year is None else str(brief.since_year)),
        ("## Iterations", str(brief.iterations)),
        ("## Per Query", str(brief.per_query)),
        ("## Web Per Query", str(brief.web_per_query)),
        ("## Scholar Per Query", str(brief.scholar_per_query)),
        ("## Full Text Top N", str(brief.full_text_top_n)),
        ("## LLM Rerank Top N", str(brief.llm_rerank_top_n)),
        ("## LLM Summary Top N", str(brief.llm_summary_top_n)),
        ("## Top K", str(brief.top_k)),
    ]
    return "\n\n".join(f"{heading}\n{body}" for heading, body in sections).strip() + "\n"


def _list_block(items: list[str]) -> str:
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)


def _read_default_program_text() -> str:
    program_path = Path(__file__).resolve().parents[2] / "program.md"
    if not program_path.exists():
        return "# Empty program\n"
    text = program_path.read_text(encoding="utf-8")
    return text if text.strip() else "# Empty program\n"


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


def _parse_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ensure_within(path: Path, base: Path, label: str) -> None:
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"path must stay inside the {label}") from exc


def _read_message(reader) -> tuple[dict, str] | None:
    line = reader.readline()
    if not line:
        return None

    stripped = line.strip()
    if not stripped:
        return _read_message(reader)

    if line.lower().startswith(b"content-length:"):
        headers: dict[str, str] = {}
        current = line
        while True:
            name, _, value = current.decode("ascii").partition(":")
            headers[name.strip().lower()] = value.strip()
            current = reader.readline()
            if not current:
                raise ValueError("unexpected EOF while reading MCP headers")
            if current in {b"\r\n", b"\n"}:
                break

        content_length = int(headers.get("content-length", "0"))
        if content_length <= 0:
            raise ValueError("missing content-length header")
        body = reader.read(content_length)
        return json.loads(body.decode("utf-8")), "content-length"

    return json.loads(stripped.decode("utf-8")), "ndjson"


def _write_message(writer, payload: dict, mode: str | None) -> None:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if mode == "ndjson":
        writer.write(body + b"\n")
        writer.flush()
        return
    writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    writer.write(body)
    writer.flush()


def _jsonrpc_error(request_id: object, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


if __name__ == "__main__":
    main(sys.argv[1:])
