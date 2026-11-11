"""SEC EDGAR tools for the due diligence agent (session T2).

Run:  export SEC_USER_AGENT="Your Name you@example.com"
      python edgar.py AAPL

Three plain functions, each returns a small dict the model can read.
Fill in the TODOs. Python 3.9: use Optional[...] / List[...], not "X | None".
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import date

import requests

HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}
CACHE = Path(__file__).parent / ".cache"
CACHE.mkdir(exist_ok=True)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# XBRL tags to try, in order. Companies don't all use the same one.
METRICS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
}


def _get_json(url: str, cache_name: Optional[str] = None) -> dict:
    """GET a URL as JSON, with an optional on-disk cache. SEC allows 10 requests/second."""
    if not HEADERS["User-Agent"]:
        raise RuntimeError("Set SEC_USER_AGENT first, e.g. 'Your Name you@example.com'")
    if cache_name:
        path = CACHE / cache_name
        if path.exists():
            return json.loads(path.read_text())
    time.sleep(0.15)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if cache_name:
        (CACHE / cache_name).write_text(json.dumps(data))
    return data


def _pad(cik) -> str:
    # TODO: return the CIK as a 10-digit zero-padded string, e.g. 320193 -> "0000320193"
    if isinstance(cik, int):
        return str(cik).zfill(10)
    elif isinstance(cik, str):
        cik = int(cik)
        return str(cik).zfill(10)
    raise NotImplementedError

def _match(v):
    # rename the SEC's keys to the ones the rest of our code uses
    return {"name": v["title"], "ticker": v["ticker"], "cik": v["cik_str"]}

def find_company(query: str) -> Dict:
    """Match a ticker or company name. Returns up to 5 matches: name, ticker, cik."""
    data = _get_json(TICKERS_URL, cache_name="company_tickers.json")
    # data looks like {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    # TODO: exact ticker match first (case-insensitive); else companies whose title contains the query
    for value in data.values():
        if value['ticker'] == query.upper():
            return {'matches':[_match(value)]}
    matches = []
    for value in data.values():
        if query.lower() in value['title'].lower():
            matches.append(_match(value))

    # TODO: return {"matches": [...]} with at most 5 entries, or {"matches": [], "note": "not found"}
    if not matches:
        return {"matches": [], "note": "not found"}
    return matches[:5]


def list_filings(cik, form: str = "10-K", limit: int = 3) -> Dict:
    """Most recent filings of one form type: date, accession number, document URL."""
    data = _get_json(SUBMISSIONS_URL.format(cik=_pad(cik)))
    recent = data["filings"]["recent"]
    # recent is "columnar": parallel lists recent["form"], recent["filingDate"],
    # recent["accessionNumber"], recent["primaryDocument"], same index = same filing.
    # TODO: walk the lists, keep rows where form matches, stop at `limit`
    filings = []
    for i in range(len(recent["form"])):
        if recent["form"][i] == form:
            url = 'https://www.sec.gov/Archives/edgar/data/' + str(int(cik)) + '/' + recent['accessionNumber'][i].replace("-","") + '/' + recent["primaryDocument"][i]
            filings.append({'form':recent["form"][i], 'filing_date':recent["filingDate"][i],'accession':recent["accessionNumber"][i], 'url':url})
            if len(filings) >= limit:
                break 
    return {'cik':int(cik), 'form':form, 'filings':filings}
    # TODO: build the URL:
    #   https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession without dashes}/{primaryDocument}
    #raise NotImplementedError

def _annual_rows(facts: dict, tag: str) -> List[dict]:
    """Full-year 10-K rows for one tag, with quarter-length figures removed."""
    rows = facts[tag]["units"].get("USD", [])
    annual = []
    for r in rows:
        # only audited annual reports, full-year values
        if r.get("form") != "10-K" or r.get("fp") != "FY":
            continue
        # revenue/income rows have a start date: drop anything shorter than ~a year
        if "start" in r:
            days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
            if days < 300:
                continue
        annual.append(r)
    return annual

def get_financials(cik, years: int = 3) -> Dict:
    """Last `years` fiscal years of key metrics from audited 10-K XBRL data."""
    facts = _get_json(FACTS_URL.format(cik=_pad(cik)))["facts"].get("us-gaap", {})
    result = {"cik": int(cik), "currency": "USD", "metrics": {}}
    for metric, tags in METRICS.items():
        # TODO: take the first tag in `tags` that exists in facts
        best = []
        for t in tags:
            if t in facts:
                rows = _annual_rows(facts, t)
                if rows and (not best or max(r["end"] for r in rows) > max(r["end"] for r in best)):
                    best = rows
        if not best:
            result["metrics"][metric] = None   # tell the model it's missing, don't guess
            continue

        annual = [r for r in rows if r.get("form") == '10-K' and r.get("fp") == 'FY']
        by_year = {}
        for r in sorted(best, key=lambda r: r["filed"]):
            by_year[r["end"]] = r

        # 3. newest years first, trimmed to `years`
        newest = sorted(by_year, reverse=True)[:years]
        result["metrics"][metric] = [
            {"fiscal_year_end": end, "value": by_year[end]["val"], "accession": by_year[end]["accn"]}
            for end in newest
        ]
    return result
        # TODO: its values live in facts[tag]["units"]["USD"], a list of dicts with
        #       keys like "end", "val", "fy", "fp", "form", "accn"
        # TODO: keep only form == "10-K" and fp == "FY"
        # HINT: the same year appears in several later 10-Ks (as a comparison column).
        #       Dedupe by "end" date so each fiscal year appears once.
        # TODO: keep the latest `years`, newest first: [{"fiscal_year_end": ..., "value": ..., "accession": ...}]
        # TODO: if no tag is found, store None so the model knows it's missing rather than guessing
        # pass
    #return result


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    hit = find_company(q)
    print(json.dumps(hit, indent=2))
    if hit.get("matches"):
        cik = hit["matches"][0]["cik"]
        print(json.dumps(list_filings(cik), indent=2))
        print(json.dumps(get_financials(cik), indent=2))
