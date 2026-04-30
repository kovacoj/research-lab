# OpenCode Project Instructions

## GitHub issue workflow

When working from a GitHub issue or PR comment:

1. Always create a pull request. Do not push directly to `main`.
2. Use `main` as the PR base branch unless explicitly instructed otherwise.
3. Create a feature branch from the current `main`.
4. Use this branch naming convention:

   `feat/<issue-number>-<short-kebab-description>`

   Examples:
   - `feat/12-accept-label-style-brief-sections`
   - `feat/27-improve-readme-heading-guidance`

5. Use Conventional Commits for all commits and PR titles.

   Format:

   `<type>(<scope>): <summary>`

   Allowed types:
   - `feat`
   - `fix`
   - `docs`
   - `test`
   - `refactor`
   - `chore`
   - `ci`

   Examples:
   - `fix(parser): accept label-style brief sections`
   - `docs(readme): clarify required brief heading syntax`
   - `test(parser): cover label-style section parsing`

6. Prefer one focused commit per issue unless the task clearly requires multiple logical commits.
7. The PR title must be a Conventional Commit title.
8. The PR description must include:
   - Summary
   - Tests run
   - Linked issue using `Closes #<issue-number>` when applicable.
9. Do not merge your own PR unless explicitly instructed in the GitHub comment.
10. If explicitly instructed to merge, use squash merge into `main` and delete the feature branch after merge.

## Merge behavior

When explicitly asked to auto-merge a PR after checks pass, use:

`gh pr merge --auto --squash --delete-branch`

Only do this when the user explicitly asks for auto-merge or merge.
