# HatsuTech Engineering Guidelines

This file is the shared engineering contract for humans, OpenAI Codex, GitHub
Copilot Code Review and other tooling that works on this repository.

HatsuTech is a source-available Discord bot for the Animes Cafe community. The
repository can be read and reviewed, but use, copying, hosting, modification,
redistribution or derivative work requires prior written authorization under
the project license.

## Workflow

Non-trivial changes should use the standard engineering flow:

Issue -> branch -> commits -> Pull Request -> review -> merge

Avoid large changes directly on `main`. Work on `main` only for explicitly
approved emergency maintenance or repository administration.

## Branches

Use short, descriptive branch names:

- `feat/<description>`
- `fix/<description>`
- `refactor/<description>`
- `docs/<description>`
- `test/<description>`
- `security/<description>`
- `chore/<description>`

## Commits

Use Conventional Commits:

- `feat:`
- `fix:`
- `refactor:`
- `test:`
- `docs:`
- `chore:`
- `build:`
- `ci:`
- `security:`

Each commit should represent one logical change. Do not create empty commits or
artificial activity.

## Pull Requests

Each PR should:

- have a clear title;
- explain the problem being solved;
- explain the implemented solution;
- include how the change was tested;
- link the related Issue when one exists;
- avoid unrelated changes;
- call out manual GitHub, Discord, MongoDB or hosting configuration.

Use draft PRs while work is still being validated.

## Testing

Before finishing a task, run the commands that actually exist for this project.
Do not claim a command passed unless it was executed.

Current baseline checks:

```bash
python -m compileall -q main.py config.py database.py utils.py cogs scripts
python -m pip check
```

When tests, linting or type checking are added later, update this file and the
CI workflow.

## Project Shape

HatsuTech is a Python Discord bot using `discord.py`, MongoDB through PyMongo,
environment variables through `python-dotenv`, and Discloud configuration.

Prefer the existing cog structure:

- `cogs/atualizacoes`
- `cogs/clashroyale`
- `cogs/economia`
- `cogs/engagement`
- `cogs/guilda`
- `cogs/moderation`
- `cogs/ranks`
- `cogs/vip`

Keep new commands close to their domain. Avoid mixing economy, VIP, moderation,
ranking and engagement logic in the same module unless there is an existing
shared helper.

## Discord Bot Rules

When changing Discord commands, listeners or background tasks:

- validate permissions before performing privileged actions;
- use ephemeral responses for admin-only feedback when appropriate;
- avoid leaking internal IDs, tokens, stack traces or private data to public
  channels;
- handle `discord.Forbidden`, `discord.NotFound` and `discord.HTTPException`;
- avoid aggressive DM broadcasts or behavior that could be treated as spam;
- respect Discord rate limits and retry hints;
- use `allowed_mentions` deliberately;
- skip bots where user-only behavior is expected;
- keep command responses clear enough for staff to operate.

## Database Rules

MongoDB access goes through the existing resilient collection wrappers in
`database.py`. Do not create ad hoc clients in bot code unless there is a
strong reason and it is documented.

When storing data:

- prefer stable string IDs for Discord IDs if that matches the existing
  collection;
- avoid storing message content unless the feature explicitly requires it;
- add indexes for new query patterns;
- keep operational logs structured and bounded;
- handle unavailable database mode gracefully when the command can degrade.

## Security

Review changes for:

- authentication and authorization;
- privileged role checks;
- user, role, guild, channel and message ID validation;
- secrets, tokens and `.env` handling;
- Discord permission hierarchy;
- mass DM or spam risk;
- data exposure in embeds, logs and errors;
- unsafe external URLs or attachments;
- user-generated text in embeds;
- rate limit and abuse paths;
- economy balance manipulation;
- VIP ownership and role recovery logic;
- third-party API failures.

Never commit Discord tokens, MongoDB URIs, API keys, private cookies, session
tokens or production credentials.

## AI Collaboration

When Codex implements a task:

1. Read the Issue or user request.
2. Inspect the relevant code and existing patterns.
3. Implement the smallest complete change.
4. Run appropriate checks.
5. Open or update a PR when requested.
6. Read GitHub Copilot comments when present.
7. Classify comments as `VALID`, `INVALID` or `NEEDS_HUMAN_DECISION`.
8. Fix valid comments with focused commits.
9. Explain technically when a suggestion does not apply.
10. Ask for human decision on product, policy or architecture tradeoffs.

Do not accept Copilot suggestions automatically. Do not change code only to
satisfy style comments that are better handled by a formatter or linter.

Limit automatic Codex/Copilot correction loops to two rounds without human
input.

