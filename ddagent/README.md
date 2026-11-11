# Due diligence agent

Give it a US-listed company. It pulls the company's financials and latest 10-K from SEC EDGAR, reads the risk, legal, MD&A and controls sections, and returns a structured risk report in which every risk is backed by a word-for-word quote and a paragraph id from the filing. An eval suite checks the reports in code against the source data.

Built from scratch on the Claude API (raw tool-use loop, no agent framework).

## How it works

```
"Peloton"
   │
   ▼
agent.py ── tool-use loop (Claude, adaptive thinking) ─────────────────────┐
   │                                                                        │
   ├─ find_company      company name/ticker → CIK        (edgar.py)         │
   ├─ list_filings      latest 10-K accession + URL      (edgar.py)         │
   ├─ get_financials    3 years of XBRL figures          (edgar.py)         │
   ├─ get_10k_section   Item 1A / 3 / 7 / 9A, paged      (tenk.py)          │
   ├─ search_10k        keyword search over those items  (tenk.py)          │
   └─ submit_report     final report, JSON schema        (report.py) ◄──────┘
                          │  invalid → errors go back to the model, it retries
                          ▼  valid   → reports/<TICKER>-<date>.json + .md
```

Every 10-K paragraph gets a stable id such as `1A-p014`. The model cites ids, and the evals look them up.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install anthropic requests beautifulsoup4 jsonschema
export ANTHROPIC_API_KEY=...                       # never commit it
export SEC_USER_AGENT="Your Name you@example.com"  # SEC requires a contact string

python agent.py "Peloton"     # writes reports/PTON-<date>.md and .json
python run_evals.py           # runs every case in eval_cases.json
```

Example output: [reports/NTCS-2026-11-11.md](reports/NTCS-2026-11-11.md), a micro-cap with a going-concern opinion and a material weakness, both found and quoted. Also [Peloton](reports/PTON-2026-11-11.md).

## Report format

`submit_report` takes the report as its input. Its schema (`report.py`) requires:
key figures (copied exactly from `get_financials`), financial flags, 1 to 8 risks (each with a category, severity, quote and citation), all 5 red flags (going concern, material weakness, restatement, auditor change, major litigation) marked found or not found with evidence, an overall rating with a rationale, and open questions for a human reviewer.

## Evals

`run_evals.py` grades every report **in code, against the source data**. No model grades another model.

| Check | Passes when |
|---|---|
| schema | the report passes `report.validate()` |
| numbers | every key figure equals what `get_financials` returned |
| citations | every cited paragraph exists and contains the quote word for word |
| red_flags | flags the case expects are marked found |
| not_found | a made-up company gives no report and the answer says "not found" |

Final run (2026-11-11): **5/5 passed**, $0.44 for the whole suite.

| Case | Pass | Turns | Cost |
|---|---|---|---|
| Apple | yes | 4 | $0.105 |
| Microsoft | yes | 4 | $0.109 |
| Peloton | yes | 4 | $0.116 |
| Made-up company | yes | 3 | $0.022 |
| Natics Corp. (expects going concern + material weakness) | yes | 5 | $0.086 |

The first Natics run failed the numbers check. The agent was right (it wrote null for figures missing from XBRL) and the eval was wrong. The check is fixed: evals need testing too.

**About 10 cents per report** (Claude Sonnet 5.5, $2 / $10 per million input / output tokens).

## Design decisions

- **The final answer is a tool call.** `submit_report` takes the report as its input, and its input schema is the report schema. The code validates it, and if it fails, the errors go back to the model so it can fix them. So the structure is guaranteed by code, not just asked for in the prompt.
- **Paragraph ids.** Every 10-K paragraph gets a stable id (e.g. 1A-p014). The model cites ids, not vague sources, so code can look up the paragraph and check the quote is in it word for word. Citations become testable instead of trust-me.
- **Schema for structure, prompt for judgement.** Anything a rule can check lives in the schema and code: all 5 red flags present, fixed categories and severities, quotes 10 to 300 characters, citation ids in the right format, evidence required when a flag is found. Anything that needs judgement lives in the prompt: which risks matter most to an investor, how severe they are, and the overall rating and its rationale.
- **Evals graded in code, not by an LLM judge.** They check against the source data (SEC figures, 10-K text). When you have ground truth, an exact check is cheaper, repeatable, and can't be talked into a pass. A judge only makes sense for the judgement parts, such as whether the right risks were chosen.
- **Nudge once.** When the model stops without submitting, the loop nudges it once to call submit_report. A second stop is accepted as the answer, so "not found" can end the run. Nudging forever would burn turns and push the model to invent a report. The made-up company case in the evals checks this.
- **No framework.** Built the loop by hand to understand what a framework hides: the growing message history, parallel tool calls and their results, errors sent back with is_error, stop reasons (end_turn, tool_use, max_tokens), retries when the report fails validation, a turn limit, and token and cost tracking. Now I know what my team gets from a framework, and what they still have to own: the tools and the data wrangling behind them, model choice, and evals.

## Limitations and next steps

- Only the latest 10-K, and only Items 1A, 3, 7 and 9A. No 10-Qs, 8-Ks or notes to the financial statements.
- `search_10k` uses plain keyword matching, so generic words like "material" match a lot. Phrase search or embeddings would help.
- XBRL data has gaps (tags change between years), so some figures show as "not available".
- The eval set is small (5 cases, one run each, one with real red flags). More red-flag cases and repeated runs would make the score more convincing.
- The model sometimes lists a positive as a "low" financial flag.

*Research, not investment advice.*
