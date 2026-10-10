# Day 01 log

**What broke?**

**What surprised you?**

**One lesson for interviews:**

**One implication for the team:**

## Things to try once it works
- Print `len(json.dumps(messages, default=str))` each turn and watch context grow.
- Make a tool fail on purpose. Does the model recover from the `is_error` result?
- Set `max_tokens=50`. What does `max_tokens` as a stop reason do to your loop?
- Ask for something needing 2 tools in parallel. How many tool_use blocks come back in one turn?
