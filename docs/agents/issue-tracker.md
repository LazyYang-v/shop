# Issue tracker: GitHub

Issues and specs live at https://github.com/LazyYang-v/docs/issues.
Use the gh CLI and explicitly target `--repo LazyYang-v/docs`;
this workspace has no Git remote from which to infer the repository.

## Conventions

- Create: `gh issue create --repo LazyYang-v/docs --title "..." --body-file <file>`
- Read: `gh issue view <number> --repo LazyYang-v/docs --json number,title,body,labels,comments`
- List: `gh issue list --repo LazyYang-v/docs --state open --json number,title,body,labels`
- Comment: `gh issue comment <number> --repo LazyYang-v/docs --body-file <file>`
- Labels: `gh issue edit <number> --repo LazyYang-v/docs --add-label "..."` / `--remove-label "..."`
- Close: `gh issue close <number> --repo LazyYang-v/docs`
- Sub-issues and dependencies: use GitHub native relationships when available.
  Otherwise record `Part of #<parent>` and `Blocked by: #<number>` in issue bodies.

When a skill says “publish to the issue tracker”, create a GitHub issue.
When it says “fetch the relevant ticket”, read the GitHub issue.

## Pull requests as a triage surface

PRs as a request surface: no.

## Wayfinding

A map is an issue labeled `wayfinder:map`.
Child tickets link to the map and use `wayfinder:<type>` labels.
Choose an open, unassigned child with no open blockers; claim by assigning
yourself. Record results in the ticket and decisions in the map.

## Prerequisites

Install gh and authenticate before remote operations.
Do not silently switch trackers if GitHub access is unavailable.

## Setup status

Local configuration is written. GitHub CLI 2.103.0 is installed and
authenticated as `LazyYang-v`. All five configured triage labels were
verified in `LazyYang-v/docs`: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, and `wontfix`.
The four missing labels were created; the existing `wontfix` label was reused.
