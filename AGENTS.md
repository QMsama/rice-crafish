# Repository workflow

## Feature development

- Treat main as the integrated, verified version of the rice-crayfish models.
- Keep year-specific code in models/2022 and models/2024. Paths in each model's SOURCE_MANIFEST are relative to that model directory.
- Start a focused feat/<year>-<feature> or fix/<year>-<issue> branch from current main before changing behavior. An existing suitable feature branch may be reused after checking its base and scope.
- Complete the implementation and appropriate verification, update the relevant CHANGELOG in the feature branch, record the model run and provenance when relevant, and request review before merging.
- Publish a PR targeting main within the user's authorized scope. Use merge commits so that feature commits and the merge point remain visible in the Git graph.
- Record the completed behavior, parameter or algorithm changes, validation, and run IDs in the relevant CHANGELOG. Use clear commit and PR notes.
- model/2022 and model/2024 retain the annual integration history. Synchronize main before continuing development on either annual branch. Ordinary new features use focused branches from main.

## Artifacts and history

- Store local work scripts, logs, previews, caches and verification records in the project's .codex-work directory; preserve source inputs and existing user changes.
- Preserve the original project .codex directory and user-level configuration.
- Keep archive/legacy-20261026 and existing commit history available for provenance.
- Report reproduction checks separately from independent observational validation.
- Follow repository protection rules and the user's explicit authorization for external writes and merges.
