# 2022 model workflow

- Base feature/fix/chore branches on model/2022; target PRs to model/2022 with merge commits.
- Keep current runtime code in models/2022; historical sources and notes belong in archive/models/2022.
- Stage only files for the requested change; use concise Conventional Commits and one model CHANGELOG.
- Preserve model rules, parameters, input provenance and user changes during archival work.
- Keep work scripts, logs, previews and caches in project .codex-work; preserve project .codex and user configuration.
- Review changes before merge. Confirm file or branch deletion separately; archive moves preserve original bytes.

## 2022 model optimization

- Active debugging branch: feat/2022-model-optimization, based on model/2022.
- Scope is the 2022 model. Keep 2024 work outside this branch.
- Keep changes and trial results on the debugging branch until the user explicitly approves merging. Do not enable auto-merge or update model/2022 or main with trial changes.
- Establish the current point and regional baselines before modifying scientific rules. Evaluate water balance, same-date water/TN observations and event loads together; do not select parameters solely to match a total load.
- Explain each change in plain Chinese: the rule, evidence, before/after results and unresolved assumptions. Present comparisons for user review before proposing integration.
