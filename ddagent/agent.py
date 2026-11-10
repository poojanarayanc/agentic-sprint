"""Day 01: a raw tool-use agent loop against the Claude API, no framework.

Run:  pip install anthropic && export ANTHROPIC_API_KEY=...
      python agent_loop.py "What files are in this folder, and how big is the largest?"

Fill in the TODOs. Each one is a thing frameworks normally hide from you.
"""

import json
import os
import subprocess
import sys

import anthropic

import edgar
MAX_TURNS = 15

MODEL = "claude-sonnet-5-5"
MAX_TURNS = 10

SYSTEM_PROMPT = """You are a due diligence analyst researching US public companies for an investor.

Process:
1. Use find_company to identify the company. If there are several matches, pick the most likely one and say which you chose. If there are none, stop and say the company was not found.
2. Use list_filings to find its most recent 10-K filings.
3. Use get_financials to get the last 3 fiscal years of key figures.
4. Then write the memo.

Memo format (markdown):
## Snapshot
Company name, ticker, CIK, latest 10-K date.
## Financial trend
A table of the 3 years for each metric, in USD billions or millions, then 2-3 sentences on the direction (growth, profitability, leverage, cash).
## Initial risk flags
Bullet points for anything that stands out in the numbers: falling revenue, losses, rising debt, low cash compared to liabilities. Mark each as low, medium or high and add a short "Why:" line naming the exact figures and years that triggered it (e.g. "Why: long-term debt rose from $X in 2024 to $Y in 2026").
## Sources
The accession number of each filing you used.

Rules:
- Only use numbers that the tools returned. Never estimate or use outside knowledge for figures.
- If a metric is null, write "not available" and don't guess.
- Keep the memo under 400 words.
- This is research, not investment advice."""

class TruncatedError(Exception):
    def __init__(self, partial_text):
        super().__init__("Response cut off at max_tokens")
        self.partial_text = partial_text

client = anthropic.Anthropic()

# 1. Tool schemas: the model only knows what you describe here.
TOOLS = [
    {"name": "find_company",
     "description": "matches a ticker or company with company names and tickers from SEC",
     "input_schema": {"type": "object",
                      "properties": {"query": {"type": "string", "description": "Ticker or company name"}},
                      "required": ["query"]}},
    {"name": "list_filings",
     "description": "returns last 3 10-K with filing date, accession number and url to the document",
     "input_schema": {"type": "object",
                      "properties": {"cik": {"type": "integer"},
                                     "form": {"type": "string", "description": "e.g. 10-K, 10-Q, 8-K"}},
                      "required": ["cik"]}},
    {"name": "get_financials",
     "description": "reads the XBRL of companies and returns the last 3 years of fiscal revenues, net income, assets, liabilities, cash and debts",
     "input_schema": {"type": "object",
                      "properties": {"cik": {"type": "integer"}},
                      "required": ["cik"]}},
]


TOOL_FUNCS = {"find_company": edgar.find_company,
              "list_filings": edgar.list_filings,
              "get_financials": edgar.get_financials}
MAX_TOOL_CHARS = 8000

def run_tool(name: str, args: dict) -> str:
    if name not in TOOL_FUNCS:
        raise ValueError(f"unknown tool {name}")
    out = json.dumps(TOOL_FUNCS[name](**args))
    if len(out) > MAX_TOOL_CHARS:          # protect the context window
        out = out[:MAX_TOOL_CHARS] + "...[truncated]"
    return out


def agent(task: str) -> str:
    # 2. Context growth: this list is the agent's entire memory. Watch it grow.
    messages = [{"role": "user", "content": task}]

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            tools=TOOLS,
            messages=messages,
        )
        print(f"[turn {turn}] stop_reason={response.stop_reason} "
              f"in={response.usage.input_tokens} out={response.usage.output_tokens}")

        # TODO: append the assistant's response to `messages`.
        #       (Hint: the whole response.content list, not just the text.)
        messages.append({"role":"assistant", "content":response.content})

        # 3. Stop reasons: decide what each one means.
        # TODO: if stop_reason is "end_turn", return the final text.
        if response.stop_reason == "end_turn":
            text = "".join(b.text for b in response.content if b.type == "text")
            return text
        # TODO: if stop_reason is "max_tokens", what should happen?
        if response.stop_reason == "max_tokens":
            text = "".join(b.text for b in response.content if b.type == "text")
            raise TruncatedError(text)

        # TODO: if stop_reason is "tool_use":
        #   - for every block where block.type == "tool_use", call run_tool
        #   - wrap each result as {"type": "tool_result", "tool_use_id": block.id, "content": ...}
        #   - if run_tool raises, send the error back with "is_error": True instead of crashing
        #   - append ONE user message holding all the tool_result blocks
        
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    print(f"  -> {block.name}({block.input})")
                    output = run_tool(block.name, block.input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
                except Exception as e:
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(e),
                        "is_error": True,
                    })
            messages.append({"role":"user","content":results})
            continue


    return "Stopped: hit MAX_TURNS without finishing."


if __name__ == "__main__":
    try:
        print(agent(" ".join(sys.argv[1:]) or "List the files here and summarise the largest one."))
    except TruncatedError as e:
        print("WARNING:", e)
        print(e.partial_text)
