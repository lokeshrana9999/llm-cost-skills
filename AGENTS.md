# LLM skill pack: instructions for Codex, Cursor and other coding agents

This folder is a pack of three skills that find where an app spends money and time on LLM calls.
You do not need a plugin system: open the skill file and follow it.

1. `skills/llm-scan/SKILL.md`: map every LLM call site into `work/<repo>/routes.json`.
2. `skills/llm-capture/SKILL.md`: turn the app's usage logs into numeric-only `work/<repo>/rows.jsonl`.
3. `skills/llm-diagnose/SKILL.md`: run `python scripts/calc.py` and map each finding to `file:function`.

Start with the user's ask ("audit my LLM usage", "why is my LLM bill high", "make my LLM calls faster"), run the skills in that order, and ask before changing anything in their repo.

Rules that always apply:

- Before each skill, read the one delegation file that matches you: `delegation/claude.md` (Claude Code) or `delegation/codex.md` (Codex / ChatGPT). It says which step uses a cheaper helper.
- All outputs go under `work/<repo>/` in this pack. Never write into the user's repo.
- Never put prompt, answer or user text into `rows.jsonl`. Ids are hashed. Nothing leaves the machine.
- Every number comes from `scripts/calc.py`. Never compute or estimate numbers yourself.
- Use `python` (not `python3` on Windows). Check the pack with `python scripts/test_calc.py`.
- `examples/` holds made-up sample rows, routes and a report (`examples/make_sample.py` generates them). They are a format reference only: never treat their numbers as the user's.
