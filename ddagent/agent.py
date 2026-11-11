"""A raw tool-use agent loop against the Claude API, no framework.

Run:  pip install anthropic && export ANTHROPIC_API_KEY=...
      python agent_loop.py "What files are in this folder, and how big is the largest?"

Fill in the TODOs. Each one is a thing frameworks normally hide from you.
"""

import json
import sys

import anthropic

import edgar
import tenk
import report
MAX_TURNS = 20
LAST_RUN = {}   # module level, next to MAX_TURNS

MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = """You are a due diligence analyst researching US public companies for an investor.

Process:
1. Use find_company to identify the company. If there are several matches, pick the most likely one and say which you chose. If there are none, stop and say the company was not found.
2. Use list_filings to find its most recent 10-K filings.
3. Use get_financials to get the last 3 fiscal years of key figures.
4. Read Item 1A with get_10k_section, and use search_10k for red flags: going concern, material weakness, restatement, auditor change, investigation, litigation. Check Items 3 and 9A.
5. Then write the memo.

Report:
When you have the financials and have read the 10-K, call submit_report once. Its schema defines the fields. Also:
- Pick the risks that matter most to an investor, not just the first ones you read.
- Base overall_rating on both the numbers and the 10-K, and explain it in rating_rationale.

Rules:
- Only use numbers that the tools returned. Never estimate or use outside knowledge for figures.
- If a metric is null, write "not available" and don't guess.
- Keep the memo under 700 words.
- This is research, not investment advice.
- Every 10-K claim must carry its id, and quotes must be copied exactly. """

class TruncatedError(Exception):
    def __init__(self, partial_text):
        super().__init__("Response cut off at max_tokens")
        self.partial_text = partial_text

client = anthropic.Anthropic()

# 1. Tool schemas: the model only knows what you describe here.
TOOLS = [
    {"name": "find_company",
     "description": "Use this first to get the company’s CIK, which the other tools need. matches a ticker or company with company names and tickers from SEC",
     "input_schema": {"type": "object",
                      "properties": {"query": {"type": "string", "description": "Ticker or company name"}},
                      "required": ["query"]}},
    {"name": "list_filings",
     "description": "Use this to get the last 3 listings using company’s CIK. returns last 3 10-K with filing date, accession number and url to the document",
     "input_schema": {"type": "object",
                      "properties": {"cik": {"type": "integer"},
                                     "form": {"type": "string", "description": "e.g. 10-K, 10-Q, 8-K"}},
                      "required": ["cik"]}},
    {"name": "get_financials",
     "description": "Use this to list the financials from the last 3 years' listings. reads the XBRL of companies and returns the last 3 years of fiscal revenues, net income, assets, liabilities, cash and debts",
     "input_schema": {"type": "object",
                      "properties": {"cik": {"type": "integer"}},
                      "required": ["cik"]}},
    {"name": "get_10k_section", 
    "description": "fetches and returns the text of a specific item from a 10-K filing for a given company CIK. You can ask for items like 1A, 3, 7 or 9A. The tool returns the text and also next_start which indicates if there is more text from that section. Use this to read through specific sections of the 10-K filing. When requesting the same section again, use the next_start value from the previous call to continue reading from where you left off. This is useful for reading long sections like item 1A (Risk Factors) or item 7 (Management’s Discussion and Analysis of Financial Condition and Results of Operations).",
    "input_schema": {"type": "object", 
                    "properties": {"cik": {"type": "integer"},
                    "item": {"type": "string", "enum": ["1A", "3", "7", "9A"]},
                    "start": {"type": "integer", "description": "paragraph to start from; use next_start from the previous call"}},
                    "required": ["cik", "item"]}},
    {"name": "search_10k", 
    "description": "Keyword search in the company's latest 10-K (Items 1A, 3, 7, 9A). Use 2-4 specific keywords, e.g. 'material weakness controls'. Returns the best-matching paragraphs with their ids.",
    "input_schema": {"type": "object", 
                    "properties": {
                    "cik": {"type": "integer"}, 
                    "query": {"type": "string"}},
                    "required": ["cik", "query"]}},
]

TOOLS.append(report.SUBMIT_TOOL)  


TOOL_FUNCS = {"find_company": edgar.find_company,
              "list_filings": edgar.list_filings,
              "get_financials": edgar.get_financials,
              "get_10k_section": tenk.get_10k_section,
              "search_10k": tenk.search_10k}
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

    LAST_RUN.clear()
    LAST_RUN.update(turns=0, input_tokens=0, output_tokens=0, report=None)
    nudged = False

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM_PROMPT,
            max_tokens=16000,
            tools=TOOLS,
            thinking={"type": "adaptive", "display": "summarized"},
            messages=messages,
        )
        LAST_RUN["turns"] += 1
        LAST_RUN["input_tokens"] += response.usage.input_tokens
        LAST_RUN["output_tokens"] += response.usage.output_tokens
        print(f"[turn {turn}] stop_reason={response.stop_reason} "
              f"in={response.usage.input_tokens} out={response.usage.output_tokens}")
    
        for block in response.content:
            if block.type == "thinking" and block.thinking:
                print(f"  [thinking] {block.thinking}")
        # TODO: append the assistant's response to `messages`.
        #       (Hint: the whole response.content list, not just the text.)
        messages.append({"role":"assistant", "content":response.content})

        # 3. Stop reasons: decide what each one means.
        # TODO: if stop_reason is "end_turn", return the final text.
        if response.stop_reason == "end_turn":
            if nudged:
                return "".join(b.text for b in response.content if b.type == "text")
            nudged = True
            messages.append({"role": "user", "content": "Now call submit_report with the final report. If the company was not found, say 'not found' instead."})
            continue
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
            final = None
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "submit_report":
                    errors = report.validate(block.input)
                    
                    if errors:
                        print(f"  !! report rejected: {errors}")
                        results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                        "content": "Report rejected. Fix these and call submit_report again:\n" + "\n".join(errors)})
                    else:
                        LAST_RUN["report"] = block.input
                        final = report.to_markdown(block.input)
                        results.append({"type": "tool_result", "tool_use_id": block.id,
                                        "content": f"Saved to {report.save(block.input)}"})
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
            if final:
                return final 
            continue


    return "Stopped: hit MAX_TURNS without finishing."


if __name__ == "__main__":
    try:
        print(agent(" ".join(sys.argv[1:]) or "Apple"))
    except TruncatedError as e:
        print("WARNING:", e)
        print(e.partial_text)
