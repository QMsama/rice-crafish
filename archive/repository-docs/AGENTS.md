# Annual model lines

- Read BRANCH_POLICY.json and select the model year before starting functional work.
- 2022 features branch from model/2022 and target PRs to model/2022. 2024 features branch from model/2024 and target PRs to model/2024.
- Each annual branch maintains its own stable code under models/<year>, settings, changelog, verification and feature merges.
- main maintains the year catalog, repository archive documentation and fixed 2026-10-26 model snapshots. Use main-based branches for catalog changes; latest stable code is maintained on each annual mainline.
- Complete implementation, appropriate verification, CHANGELOG updates and review on the selected feature branch; use merge commits within the user's authorized scope.
- Shared algorithm changes are adapted, verified and submitted separately to the relevant annual mainlines.
- Preserve model provenance, archives and commit history. Keep local work scripts, logs, caches and verification artifacts under the project's .codex-work; preserve existing project .codex and user configuration.
- Report calculation reproduction separately from observational validation.
