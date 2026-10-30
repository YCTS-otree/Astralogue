# Astralogue project instructions

- Python >=3.11, uv, Typer, Rich, SQLite, pytest. Prefer the existing `.venv`.
- Build-time adapters must remain separate from runtime. Runtime only reads StoryPack.
- Never infer cross-sequence control from array/file/ID order. Unknown control must block.
- Do not commit upstream resources, research snapshots, generated packs, caches or saves.
- Run `.venv\Scripts\python.exe -m pytest -q` on Windows (Linux: `.venv/bin/python -m pytest -q`).
- Real integration tests use `ASTRALOGUE_HSR_SOURCE` (MVP), `ASTRALOGUE_HSR_BATCH_SOURCE` (visitor corpus), and `ASTRALOGUE_HSR_MAINLINE_SOURCE` (M5), as appropriate; missing resources must be reported as skipped.
- M5 coverage must separate full missions, hidden technical records, submission fragments, and performance fragments. Static extraction is not Runtime completion.
- Keep code, pyproject, changelog and release metadata versions consistent. Schema and save versions are separate.
- Never retrieve private-key contents. Security rules from the user's global AGENTS.md remain mandatory.
