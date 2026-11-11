"""The structured risk report (session M2).
 
The agent finishes by calling the submit_report tool. Its input must match
REPORT_SCHEMA. We validate it in code: if it fails, the errors go back to the
model as an is_error tool result and it tries again. If it passes, we save the
JSON and a readable markdown memo under reports/.
 
  pip install jsonschema
"""
import json
from datetime import date
from pathlib import Path
from typing import Dict, List
 
from jsonschema import Draft202012Validator
 
REPORTS = Path(__file__).parent / "reports"
 
SEVERITY = {"type": "string", "enum": ["low", "medium", "high"]}
CITATION = {"type": "string", "pattern": r"^(1A|3|7|9A)-p\d{3}$",
            "description": "Paragraph id from get_10k_section or search_10k, e.g. 1A-p014"}
QUOTE = {"type": "string", "minLength": 10, "maxLength": 300,
         "description": "Copied word for word from the cited paragraph, under 25 words"}
 
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["company", "filing", "key_figures", "financial_flags", "risks",
                 "red_flags", "overall_rating", "rating_rationale", "open_questions"],
    "properties": {
        "company": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "ticker", "cik"],
            "properties": {"name": {"type": "string"}, "ticker": {"type": "string"},
                           "cik": {"type": "integer"}},
        },
        "filing": {
            "type": "object", "additionalProperties": False,
            "required": ["accession", "filing_date"],
            "properties": {"accession": {"type": "string"}, "filing_date": {"type": "string"}},
        },
        "key_figures": {
            "type": "array", "minItems": 1,
            "description": "Numbers exactly as get_financials returned them, in USD (not billions).",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["metric", "fiscal_year_end", "value"],
                "properties": {
                    "metric": {"type": "string", "enum": ["revenue", "net_income", "total_assets",
                                                          "total_liabilities", "cash", "long_term_debt"]},
                    "fiscal_year_end": {"type": "string"},
                    "value": {"type": ["number", "null"]},
                },
            },
        },
        "financial_flags": {
            "type": "array",
            "description": "Concerns from the numbers only. Empty list if there are none.",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["severity", "finding", "why"],
                "properties": {"severity": SEVERITY, "finding": {"type": "string"},
                               "why": {"type": "string"}},
            },
        },
        "risks": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["category", "severity", "finding", "evidence_quote", "citation"],
                "properties": {
                    "category": {"type": "string", "enum": ["financial", "legal", "operational",
                                                            "governance", "market", "regulatory"]},
                    "severity": SEVERITY,
                    "finding": {"type": "string"},
                    "evidence_quote": QUOTE,
                    "citation": CITATION,
                },
            },
        },
        "red_flags": {
            "type": "array", "minItems": 5, "maxItems": 5,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["flag", "status"],
                "properties": {
                    "flag": {"type": "string", "enum": ["going_concern", "material_weakness", "restatement",
                                                        "auditor_change", "major_litigation"]},
                    "status": {"type": "string", "enum": ["found", "not_found"]},
                    "evidence_quote": QUOTE,
                    "citation": CITATION,
                },
                # if a flag is found, it must come with evidence
                "if": {"properties": {"status": {"const": "found"}}},
                "then": {"required": ["evidence_quote", "citation"]},
            },
        },
        "overall_rating": SEVERITY,
        "rating_rationale": {"type": "string"},
        "open_questions": {"type": "array", "items": {"type": "string"},
                           "description": "What a human reviewer should check next"},
    },
}
 
_validator = Draft202012Validator(REPORT_SCHEMA)
 
 
def validate(rep: Dict) -> List[str]:
    """Readable error messages; an empty list means the report is valid."""
    errors = []
    for e in sorted(_validator.iter_errors(rep), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in e.path) or "(top level)"
        errors.append(f"{where}: {e.message}")
    flags = [f["flag"] for f in rep.get("red_flags", []) if isinstance(f, dict)]
    if len(flags) == 5 and len(set(flags)) != 5:
        errors.append("red_flags: each of the 5 flags must appear exactly once")
    return errors
 
 
def _money(v) -> str:
    if v is None:
        return "not available"
    return f"{v / 1e9:,.1f}B" if abs(v) >= 1e8 else f"{v / 1e6:,.1f}M"
 
 
def to_markdown(rep: Dict) -> str:
    c, f = rep["company"], rep["filing"]
    lines = [f"# Due diligence: {c['name']} ({c['ticker']})", "",
             f"CIK {c['cik']} · 10-K filed {f['filing_date']} · accession {f['accession']}", "",
             f"**Overall risk: {rep['overall_rating'].upper()}.** {rep['rating_rationale']}", ""]
 
    years = sorted({k["fiscal_year_end"] for k in rep["key_figures"]})
    metrics = []
    for k in rep["key_figures"]:
        if k["metric"] not in metrics:
            metrics.append(k["metric"])
    lookup = {(k["metric"], k["fiscal_year_end"]): k["value"] for k in rep["key_figures"]}
    lines += ["## Key figures (USD)", "",
              "| Metric | " + " | ".join(years) + " |",
              "|---|" + "---|" * len(years)]
    for m in metrics:
        lines.append(f"| {m.replace('_', ' ')} | " +
                     " | ".join(_money(lookup.get((m, y))) for y in years) + " |")
 
    lines += ["", "## Financial flags", ""]
    lines += [f"- **{x['severity'].title()}:** {x['finding']} Why: {x['why']}" for x in rep["financial_flags"]] \
        or ["- None from the numbers."]
 
    lines += ["", "## Risks from the 10-K", ""]
    for r in rep["risks"]:
        lines.append(f"- **{r['severity'].title()} · {r['category']}:** {r['finding']} "
                     f"\"{r['evidence_quote']}\" [{r['citation']}]")
 
    lines += ["", "## Red flags", ""]
    for x in rep["red_flags"]:
        name = x["flag"].replace("_", " ").capitalize()
        if x["status"] == "found":
            lines.append(f"- **{name}: found.** \"{x['evidence_quote']}\" [{x['citation']}]")
        else:
            lines.append(f"- {name}: not found.")
 
    lines += ["", "## Open questions for a reviewer", ""]
    lines += [f"- {q}" for q in rep["open_questions"]] or ["- None."]
    lines += ["", "*Research, not investment advice.*"]
    return "\n".join(lines)
 
 
def save(rep: Dict) -> Path:
    """Write reports/<ticker>-<date>.json and .md; returns the markdown path."""
    REPORTS.mkdir(exist_ok=True)
    stem = REPORTS / f"{rep['company']['ticker'].upper()}-{date.today().isoformat()}"
    stem.with_suffix(".json").write_text(json.dumps(rep, indent=2))
    md = stem.with_suffix(".md")
    md.write_text(to_markdown(rep))
    return md
 
 
def _for_api(schema):
    """Copy of the schema without if/then, which we enforce in validate() instead."""
    if isinstance(schema, dict):
        return {k: _for_api(v) for k, v in schema.items() if k not in ("if", "then")}
    if isinstance(schema, list):
        return [_for_api(v) for v in schema]
    return schema
 
 
# The tool definition the agent sees. Its input_schema IS the report schema.
SUBMIT_TOOL = {
    "name": "submit_report",
    "description": ("Submit the final due diligence report. Call this exactly once, at the end, "
                    "after you have gathered financials and read the 10-K. If it returns errors, "
                    "fix them and call it again. A red flag marked found needs evidence_quote and citation."),
    "input_schema": _for_api(REPORT_SCHEMA),
}
 