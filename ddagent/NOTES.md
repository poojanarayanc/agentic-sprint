# DD agent log

## 2026-11-10 (T1–T3)
**Built:** edgar.py (find_company, list_filings, get_financials) + agent loop with system prompt. First end-to-end memo on Apple; all numbers match SEC data.

**What broke:** expired API key; my own Python bugs in find_company (wrong return shape, str + int).

**What surprised me:** how messy XBRL is: years repeat across filings, tag names change. Both fail silently.

**Interview lesson:** prompt shapes behaviour, code guarantees it (e.g. thinking display, null → "not available").

**Fix tomorrow:**
1. Prompt lists good news as risks; only list concerns.
2. Cash ignores investments; needs 10-K text (M1).
3. Thinking lines didn't print; check the setting.