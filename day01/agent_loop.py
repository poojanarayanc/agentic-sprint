"""Day 01: a raw tool-use agent loop against the Claude API, no framework.

Run:  pip install anthropic && export ANTHROPIC_API_KEY=...
      python agent_loop.py "What files are in this folder, and how big is the largest?"

Fill in the TODOs. Each one is a thing frameworks normally hide from you.
"""
from anthropic.types import stop_reason
import json
import os
import subprocess
import sys

import anthropic

MODEL = "claude-sonnet-5-5"
MAX_TURNS = 10

class TruncatedError(Exception):
    def __init__(self, partial_text):
        super().__init__("Response cut off at max_tokens")
        self.partial_text = partial_text

client = anthropic.Anthropic()

# 1. Tool schemas: the model only knows what you describe here.
TOOLS = [
    {
        "name": "list_files",
        "description": "List files in a directory with their sizes in bytes.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file and return its contents (first 5,000 characters).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    # TODO: add a third tool of your own (e.g. word_count, run_python). Keep it safe.
    {
        "name": "word_count",
        "description": "Read a text file and return the word count (from the first 5,000 characters)",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    }
]


def run_tool(name: str, args: dict) -> str:
    """Execute a tool call and return its result as a string."""
    if name == "list_files":
        entries = []
        for entry in os.scandir(args["path"]):
            size = entry.stat().st_size if entry.is_file() else "-"
            entries.append(f"{entry.name}\t{size}")
        return "\n".join(entries) or "(empty)"
    if name == "read_file":
        with open(args["path"], error="replace") as f:
            return f.read(5000)
    # TODO: handle your third tool
    if name == "word_count":
        with open(args["path"], error="replace") as f:
            text = f.read(5000)
            count = len(text.split())
            return str(count)
    raise ValueError(f"unknown tool {name}")


def agent(task: str) -> str:
    # 2. Context growth: this list is the agent's entire memory. Watch it grow.
    messages = [{"role": "user", "content": task}]

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
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
            return text

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
        print(str(e))
