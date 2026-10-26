# 2022 model workflow

- Base feature/fix/chore branches on model/2022; target PRs to model/2022 with merge commits.
- Keep current runtime code in models/2022; historical sources and notes belong in archive/models/2022.
- Stage only files for the requested change; use concise Conventional Commits and one model CHANGELOG.
- Preserve model rules, parameters, input provenance and user changes during archival work.
- Keep work scripts, logs, previews and caches in project .codex-work; preserve project .codex and user configuration.
- Review changes before merge. Confirm file or branch deletion separately; archive moves preserve original bytes.
