from __future__ import annotations

import sqlite3
from pathlib import Path

from research_lab.models import RunArtifacts


def init_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                topic TEXT NOT NULL,
                run_dir TEXT NOT NULL,
                query_count INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                run_id TEXT NOT NULL,
                rank_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source_names TEXT NOT NULL,
                score REAL NOT NULL,
                year INTEGER,
                venue TEXT NOT NULL,
                doi TEXT NOT NULL,
                PRIMARY KEY (run_id, rank_index)
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def record_run(path: Path, artifacts: RunArtifacts) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, created_at, topic, run_dir, query_count, candidate_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifacts.run_id,
                artifacts.created_at,
                artifacts.brief.topic,
                artifacts.run_dir,
                len(artifacts.queries),
                len(artifacts.candidates),
            ),
        )
        connection.execute("DELETE FROM candidates WHERE run_id = ?", (artifacts.run_id,))
        for index, candidate in enumerate(artifacts.candidates[: artifacts.brief.top_k], start=1):
            connection.execute(
                """
                INSERT INTO candidates (run_id, rank_index, title, url, source_names, score, year, venue, doi)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifacts.run_id,
                    index,
                    candidate.title,
                    candidate.url or candidate.open_access_url,
                    ",".join(candidate.source_names),
                    candidate.score,
                    candidate.year,
                    candidate.venue,
                    candidate.doi,
                ),
            )
        connection.commit()
    finally:
        connection.close()
