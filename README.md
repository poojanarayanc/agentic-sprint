# Agentic Engineering Sprint

Eleven days, one agent build a day. Each day pairs the build with what it teaches for interviews and what it means for leading a team.

| Day | Build | Folder |
|----|----|----|
| 01 | Agent loop from scratch | `day01/` |
| 02 | Project memory and conventions (EXIF photo CLI) | `day02/` |
| 03 | MCP server for filings / company data | `day03/` |
| 04 | Retrieval with page-level citations | `day04/` |
| 05 | Evals for Day 4 | `day05/` |
| 06 | Subagents and orchestration | `day06/` |
| 07 | Hooks and guardrails | `day07/` |
| 08 | Browser or computer use | `day08/` |
| 09 | Unattended agent (news digest) | `day09/` |
| 10 | Observability and cost | `day10/` |
| 11 | Synthesis: operating model | `day11/` |

Each day folder has the code and a `NOTES.md` log: what broke, what surprised me, one interview lesson, one team implication.

## Setup

```sh
python -m venv .venv && source .venv/bin/activate
pip install anthropic
export ANTHROPIC_API_KEY=...
```
