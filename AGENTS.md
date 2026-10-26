# 2022 annual mainline

- The stable model branch is model/2022. Read BRANCH_POLICY.json before creating a branch or PR.
- Create feat/2022-<feature>, fix/2022-<issue>, or chore/2022-<task> from current model/2022; target PRs to model/2022.
- Keep this annual model in models/2022. Complete verification, update its CHANGELOG in the feature branch, and obtain code review before merging within the user's authorization.
- Use merge commits to retain feature history and merge points. Verify both the PR head and its model/2022 base before merging.
- Each annual model has its own stable line, settings and validation. Shared changes are adapted and reviewed separately for each year. main maintains the catalog and archive documentation.
- Preserve existing model source bytes during repository-only changes; model SOURCE_MANIFEST paths are relative to models/2022.
- Keep work scripts, logs, caches, previews and verification artifacts under the project's .codex-work. Preserve original inputs, the project .codex, user configuration and existing history.
- Distinguish computation reproduction from independent observational validation.
