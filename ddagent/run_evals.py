"""Evals for the due diligence agent (session M4).
 
Runs the agent on each case in eval_cases.json and scores the result IN CODE,
against the source data. No model grades another model here.
 
  python run_evals.py              # all cases
  python run_evals.py Apple        # only cases whose query contains "Apple"
 
Checks per report:
  schema     the report passes report.validate()
  numbers    every key_figure equals what get_financials returned (exact match)
  citations  every cited paragraph exists, and its quote appears in it word for word
  red_flags  flags you listed as expected in the case are marked "found"
  not_found  for a made-up company: no report, and the answer says "not found"
 
Results are saved to eval_results/<timestamp>.json with tokens and cost per run.
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
 
import agent
import edgar
import report
import tenk
 
HERE = Path(__file__).parent
CASES = HERE / "eval_cases.json"
RESULTS = HERE / "eval_results"
 
# Claude Sonnet 5.5 list prices, USD per million tokens
PRICE_IN, PRICE_OUT = 2.00, 10.00
 
 
def _norm(s: str) -> str:
    """Compare quotes fairly: same quote marks, spacing and case."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("…", "...").replace('"', "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" .,;:...")
 
 
def check_numbers(rep):
    truth = edgar.get_financials(rep["company"]["cik"])["metrics"]
    expected = {}
    for metric, rows in truth.items():
        for r in rows or []:
            expected[(metric, r["fiscal_year_end"])] = r["value"]
    wrong = []
    for k in rep["key_figures"]:
        key = (k["metric"], k["fiscal_year_end"])
        if key not in expected:
            wrong.append(f"{key} not returned by get_financials")
        elif k["value"] != expected[key]:
            wrong.append(f"{key}: report {k['value']} vs source {expected[key]}")
    return wrong
 
 
def check_citations(rep):
    cik = rep["company"]["cik"]
    items = [r for r in rep["risks"]] + [f for f in rep["red_flags"] if f.get("citation")]
    bad = []
    for it in items:
        para = tenk.get_paragraph(cik, it["citation"])
        if para is None:
            bad.append(f"{it['citation']}: paragraph does not exist")
        elif _norm(it["evidence_quote"]) not in _norm(para):
            bad.append(f"{it['citation']}: quote not found word for word: \"{it['evidence_quote'][:80]}\"")
    return bad, len(items)
 
 
def run_case(case):
    t0 = time.time()
    try:
        text = agent.agent(case["query"])
        error = None
    except Exception as e:                      # a crash is a failed case, not a crashed eval run
        text, error = "", f"{type(e).__name__}: {e}"
    run = dict(agent.LAST_RUN)
    rep = run.get("report")
    checks = {}
 
    if case.get("expect_not_found"):
        checks["not_found"] = {"pass": rep is None and "not found" in (text or "").lower(),
                               "detail": (text or error or "")[:200]}
    elif error or rep is None:
        checks["report_produced"] = {"pass": False, "detail": error or "agent finished without a valid report"}
    else:
        errs = report.validate(rep)
        checks["schema"] = {"pass": not errs, "detail": errs[:3]}
        wrong = check_numbers(rep)
        checks["numbers"] = {"pass": not wrong, "detail": wrong[:5]}
        bad, total = check_citations(rep)
        checks["citations"] = {"pass": not bad, "detail": f"{total - len(bad)}/{total} exact. " + "; ".join(bad[:3])}
        expected = set(case.get("expect_red_flags_found", []))
        if expected:
            found = {f["flag"] for f in rep["red_flags"] if f["status"] == "found"}
            missing = expected - found
            checks["red_flags"] = {"pass": not missing, "detail": f"missing: {sorted(missing)}" if missing else "ok"}
 
    tin, tout = run.get("input_tokens", 0), run.get("output_tokens", 0)
    return {
        "query": case["query"],
        "passed": all(c["pass"] for c in checks.values()),
        "checks": checks,
        "turns": run.get("turns"),
        "input_tokens": tin,
        "output_tokens": tout,
        "cost_usd": round(tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT, 4),
        "seconds": round(time.time() - t0, 1),
    }
 
 
def main():
    cases = json.loads(CASES.read_text())
    if len(sys.argv) > 1:
        cases = [c for c in cases if sys.argv[1].lower() in c["query"].lower()]
    results = []
    for c in cases:
        print(f"\n===== {c['query']} =====")
        results.append(run_case(c))
 
    print("\n\nRESULTS")
    print(f"{'case':<28}{'pass':<6}{'turns':<7}{'cost $':<9}checks")
    for r in results:
        marks = " ".join(f"{k}:{'ok' if v['pass'] else 'FAIL'}" for k, v in r["checks"].items())
        print(f"{r['query'][:27]:<28}{'yes' if r['passed'] else 'NO':<6}{str(r['turns']):<7}{r['cost_usd']:<9}{marks}")
        for k, v in r["checks"].items():
            if not v["pass"]:
                print(f"    {k}: {v['detail']}")
    n_pass = sum(r["passed"] for r in results)
    total_cost = sum(r["cost_usd"] for r in results)
    print(f"\nScore: {n_pass}/{len(results)} cases passed · total cost ${total_cost:.3f} "
          f"· avg ${total_cost / max(len(results), 1):.3f} per run")
 
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M}.json"
    out.write_text(json.dumps({"score": f"{n_pass}/{len(results)}", "results": results}, indent=2))
    print(f"Saved {out}")
 
 
if __name__ == "__main__":
    main()
 