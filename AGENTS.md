# Astralogue project instructions

- Python >=3.11, uv, Typer, Rich, SQLite, pytest. Prefer the existing `.venv`.
- Build-time adapters must remain separate from runtime. Runtime only reads StoryPack.
- Never infer cross-sequence control from array/file/ID order. Unknown control must block.
- Do not commit upstream resources, research snapshots, generated packs, caches or saves.
- Run `.venv\Scripts\python.exe -m pytest -q` on Windows (Linux: `.venv/bin/python -m pytest -q`).
- Real integration tests require `ASTRALOGUE_HSR_SOURCE`; missing resources must be reported as skipped.
- Keep code, pyproject, changelog and release metadata versions consistent. Schema and save versions are separate.
- Never retrieve private-key contents. Security rules from the user's global AGENTS.md remain mandatory.
