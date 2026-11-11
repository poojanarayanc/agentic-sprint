"""Read a company's latest 10-K as numbered paragraphs (session M1).

Two tools for the agent:
  get_10k_section(cik, item)   one section (1A risks, 3 legal, 7 MD&A, 9A controls), paged
  search_10k(cik, query)       keyword search across those sections

Every paragraph gets a stable id like "1A-p014" so the agent can cite it and
the evals can check the citation later.

Run:  python tenk.py AAPL            (prints section sizes and a sample search)
"""
import json
import re
import sys
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

import edgar

SECTIONS = {
    "1A": "Risk Factors",
    "3": "Legal Proceedings",
    "7": "Management's Discussion and Analysis",
    "9A": "Controls and Procedures",
}

# A heading block looks like "Item 1A. Risk Factors" or "ITEM 7 - MANAGEMENT'S ...".
HEADING = re.compile(r"^item\s+(\d{1,2}[a-c]?)\b", re.IGNORECASE)
MAX_HEADING_LEN = 200     # longer blocks are sentences that mention an item, not headings
MIN_PARAGRAPH_LEN = 25    # drop page numbers, "Table of Contents" links and other scraps

STOPWORDS = set("the and for that with this from are was were have has had not but our its their "
                "any may can could would will such than into which also other these those been".split())


# ---------- fetching and parsing ----------

def _get_html(url: str) -> str:
    # same SEC rules as edgar.py: contact string required, stay under 10 requests/second
    if not edgar.HEADERS["User-Agent"]:
        raise RuntimeError("Set SEC_USER_AGENT first, e.g. 'Your Name you@example.com'")
    time.sleep(0.15)
    resp = requests.get(url, headers=edgar.HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.text


def _blocks(html: str) -> List[str]:
    """The document as a list of text blocks in reading order.

    A block is an element like <p> or <div> that holds text but no other block
    inside it. That gives roughly one block per paragraph, heading or table row,
    which works for the inline-XBRL HTML that 10-Ks are filed in.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    block_tags = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]
    out = []
    for el in soup.find_all(block_tags):
        if el.find(block_tags):          # has a block inside it: its children will be visited
            continue
        text = el.get_text(" ", strip=True).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append(text)
    return out


def _split_sections(blocks: List[str]) -> Dict[str, List[str]]:
    """Map item code -> its blocks, for the items in SECTIONS.

    "Item 1A" appears several times: in the table of contents, in cross-references
    ("see Item 1A") and as the real heading. We take the occurrence that starts
    the longest run of text before the next heading. The table-of-contents entry
    is followed almost at once by "Item 1B", so it always loses.
    """
    heads = []                           # (block index, item code)
    for i, b in enumerate(blocks):
        m = HEADING.match(b)
        if m and len(b) <= MAX_HEADING_LEN:
            heads.append((i, m.group(1).upper()))

    sections = {}
    for code in SECTIONS:
        best = []
        for n, (start, item) in enumerate(heads):
            if item != code:
                continue
            end = len(blocks)
            for later_start, later_item in heads[n + 1:]:
                if later_item != code:
                    end = later_start
                    break
            body = blocks[start + 1:end]
            if sum(len(b) for b in body) > sum(len(b) for b in best):
                best = body
        sections[code] = best
    return sections


def _paragraphs(code: str, blocks: List[str]) -> List[Dict]:
    paras = []
    for b in blocks:
        if len(b) < MIN_PARAGRAPH_LEN or b.lower().startswith("table of contents"):
            continue
        paras.append({"id": f"{code}-p{len(paras) + 1:03d}", "text": b})
    return paras


def load_10k(cik) -> Dict:
    """Latest 10-K, split into sections of numbered paragraphs. Cached on disk."""
    filing = edgar.list_filings(cik, form="10-K", limit=1)["filings"]
    if not filing:
        raise ValueError(f"No 10-K found for CIK {cik}")
    filing = filing[0]
    cache_file = edgar.CACHE / f"10k-{filing['accession']}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    sections = _split_sections(_blocks(_get_html(filing["url"])))
    doc = {
        "cik": int(cik),
        "filing": filing,
        "sections": {code: _paragraphs(code, blocks) for code, blocks in sections.items()},
    }
    cache_file.write_text(json.dumps(doc))
    return doc


def get_paragraph(cik, paragraph_id: str) -> Optional[str]:
    """Text of one paragraph by id, e.g. "1A-p014". Used by the evals to check citations."""
    code = paragraph_id.split("-p")[0]
    for p in load_10k(cik)["sections"].get(code, []):
        if p["id"] == paragraph_id:
            return p["text"]
    return None


# ---------- the two agent tools ----------

def get_10k_section(cik, item: str, start: int = 0, max_chars: int = 6000) -> Dict:
    """Paragraphs of one 10-K section, from paragraph `start`, up to about max_chars of text."""
    item = item.upper().replace("ITEM", "").strip()
    if item not in SECTIONS:
        raise ValueError(f"item must be one of {list(SECTIONS)}")
    doc = load_10k(cik)
    paras = doc["sections"][item]
    picked, size, i = [], 0, start
    while i < len(paras) and (size < max_chars or not picked):
        picked.append(paras[i])
        size += len(paras[i]["text"])
        i += 1
    return {
        "cik": int(cik),
        "item": item,
        "title": SECTIONS[item],
        "filing_date": doc["filing"]["filing_date"],
        "accession": doc["filing"]["accession"],
        "total_paragraphs": len(paras),
        "paragraphs": picked,
        "next_start": i if i < len(paras) else None,   # call again with start=next_start to read on
        "note": None if paras else "Section not found or empty in this filing.",
    }


def _terms(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOPWORDS]


def search_10k(cik, query: str, top_k: int = 8) -> Dict:
    """Paragraphs across all sections that best match the query's keywords."""
    doc = load_10k(cik)
    q = set(_terms(query))
    if not q:
        raise ValueError("query has no searchable words")
    scored = []
    for code, paras in doc["sections"].items():
        for p in paras:
            words = _terms(p["text"])
            hits = q.intersection(words)
            if not hits:
                continue
            # distinct query words matter most; repeats break ties
            score = len(hits) + 0.01 * sum(words.count(w) for w in hits)
            scored.append((score, p))
    scored.sort(key=lambda s: s[0], reverse=True)
    return {
        "cik": int(cik),
        "query": query,
        "accession": doc["filing"]["accession"],
        "results": [{"id": p["id"], "score": round(s, 2), "text": p["text"][:1200]}
                    for s, p in scored[:top_k]],
    }


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    cik = edgar.find_company(q)["matches"][0]["cik"]
    doc = load_10k(cik)
    print("Filing:", doc["filing"]["filing_date"], doc["filing"]["url"])
    for code, paras in doc["sections"].items():
        first = paras[0]["text"][:90] if paras else "(empty)"
        print(f"  Item {code:<3} {len(paras):>4} paragraphs | {first}")
    print(json.dumps(search_10k(cik, "material weakness going concern litigation", top_k=3), indent=2)[:5000])
