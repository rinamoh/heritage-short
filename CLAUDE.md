@AGENTS.md

## Claude Code specifics
- Read DESIGN.md, ETHICS.md and storyboard.json before changing anything in pipeline/.
- Write and fix code; don't run long pipeline commands yourself (`python run.py`, full stages). Tell me the exact command and I'll run it in my terminal and paste the output back. Short checks (`python -m pipeline.validate`, a quick import test) are fine.
- Never run `git commit` or `git push`. I review the diff and commit myself.
- Narration is finished (9 Addis AI WAVs in outputs/narration, all cached). Never regenerate a line whose text or settings haven't changed.