# OpenCode Agents

These prompts are meant for running OpenCode inside this repository.

This repo is agent-first. The prompts in `.opencode/agents/` are the main operating surface. The Python CLI is optional tooling that an agent may invoke when it helps.

The current lab supports arXiv, OpenAlex, Semantic Scholar, DuckDuckGo, and an experimental Google Scholar scraping path when explicitly enabled.

- `agents/lab-director.md`: primary orchestration prompt for the whole lab.
- `agents/brief-structurer.md`: turns messy notes into a parser-friendly `brief.md`.
- `agents/run-reviewer.md`: reviews a completed run and compares it against a prior run.
- `agents/evidence-hunter.md`: digs for sources that support or challenge a specific claim.

They are plain prompt files so you can copy them into an OpenCode session or adapt them into your local workflow.
