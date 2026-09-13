# AI Development Workflow

This document describes how HatsuTech should be maintained through real
engineering work between humans, OpenAI Codex and GitHub Copilot Code Review.

Do not create artificial commits, issues, pull requests or reviews just to
increase activity metrics. Every change must represent a real improvement,
maintenance task, documentation update, test, security hardening or bug fix.

## Standard Flow

```text
Developer or Codex
        |
      Issue
        |
     Branch
        |
    Commits
        |
       PR
    /      \
   CI   Copilot Review
    \      /
 Codex analyzes feedback
        |
    Corrections
        |
    New push
        |
 Copilot re-review
        |
 Human review
        |
      Merge
```

## Issues

Use the repository issue forms:

- Bug report
- Feature request
- Refactor
- Security improvement

Critical vulnerabilities should not be disclosed in public issues. Use GitHub
private vulnerability reporting or contact the maintainer privately.

## Branches

Create branches from `main` using:

- `feat/<description>`
- `fix/<description>`
- `refactor/<description>`
- `docs/<description>`
- `test/<description>`
- `security/<description>`
- `chore/<description>`

## Pull Requests

Pull requests are the protocol between humans, Codex and Copilot.

Each PR should explain:

- what changed;
- why it changed;
- how it was tested;
- which issue it closes;
- what manual configuration is still needed.

Draft PRs are preferred while a change is still being validated.

## Codex Review Handling

When Copilot comments on a PR, Codex should classify each relevant comment:

- `VALID`: implement the fix, run checks, commit and push.
- `INVALID`: explain why the suggestion does not apply.
- `NEEDS_HUMAN_DECISION`: pause the decision and ask a maintainer.

Codex should not automatically accept Copilot suggestions without checking the
project context. Limit automatic correction loops to two rounds before asking
for human review.

## CI

The current CI validates the existing Python project without inventing missing
test or lint commands:

```bash
python -m compileall -q main.py config.py database.py utils.py cogs scripts
python -m pip check
```

When dedicated tests, linting or type checking are added, update:

- `.github/workflows/ci.yml`
- `AGENTS.md`
- this document

## CodeQL

CodeQL is configured for Python and runs on:

- pull requests targeting `main`;
- pushes to `main`;
- a weekly schedule;
- manual workflow dispatch.

## Dependabot

Dependabot is configured for:

- Python dependencies in `requirements.txt`;
- GitHub Actions.

Dependabot must open PRs for review. Do not enable automatic merge for security
or dependency changes unless the maintainer explicitly decides to do so later.

## Manual GitHub Settings

Some repository settings are not fully represented by files and must be enabled
manually in GitHub.

Recommended branch protection or ruleset for `main`:

- require Pull Request before merge;
- require status checks to pass;
- require the CI workflow;
- require CodeQL when available;
- require branches to be up to date before merge when appropriate;
- require conversation resolution before merge;
- require CODEOWNERS review if maintainers want strict ownership;
- restrict direct pushes to `main` when the team is ready.

Recommended Copilot settings:

- enable GitHub Copilot Code Review for pull requests;
- enable review of new pushes if available;
- keep `AGENTS.md` and `.github/copilot-instructions.md` as the review context.

Recommended security settings:

- enable private vulnerability reporting;
- enable Dependabot alerts;
- enable Dependabot security updates if desired, without auto-merge;
- review repository secrets and environment protection rules.

Do not use GitHub Actions to impersonate Copilot or to create fake reviews.

## Human Review

Human review remains required for:

- security-sensitive changes;
- economy balance or reward logic;
- VIP ownership and role recovery changes;
- moderation permissions;
- mass notification or DM behavior;
- deploy and hosting configuration;
- product decisions that affect the Animes Cafe community.

