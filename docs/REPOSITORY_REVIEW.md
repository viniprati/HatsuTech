# Repository Review

HatsuTech is source-available for reading and review only. This document helps
reviewers inspect repository changes without granting permission to use, host,
operate, copy, modify, redistribute or create derivative works from the bot.

The license remains the source of truth for allowed and prohibited use.

## Review Scope

Reviewers may inspect:

- documentation changes;
- GitHub Actions workflows;
- dependency changes;
- command permission checks;
- security-sensitive logic;
- privacy and data-handling behavior;
- pull request diffs;
- static syntax and configuration issues.

Review does not imply authorization to run the official bot, connect to
production services, reuse command flows or deploy a separate instance.

## Secrets And Private Data

Never request, publish or commit:

- Discord bot tokens;
- MongoDB URIs;
- Clash Royale API keys;
- `.env` files;
- private logs;
- private user, server or staff data;
- hosting credentials.

If a review needs sensitive context, use a private maintainer channel instead
of public issues or pull request comments.

## Static Validation

When reviewing a PR, prefer checks that inspect the repository without using
production credentials.

Useful static checks include:

```bash
git diff --check
python -m compileall -q main.py config.py database.py utils.py cogs scripts
ruby -e 'require "yaml"; files = Dir[".github/**/*.yml"] + Dir[".github/**/*.yaml"]; files.sort.each { |file| YAML.load_file(file); puts "valid #{file}" }'
```

Only state that a check passed if it was actually executed.

## Pull Request Review Focus

For code changes, focus on:

- authorization and role checks;
- Discord permission hierarchy;
- economy balance changes and audit logs;
- VIP ownership and recovery behavior;
- moderation command safety;
- handling of Discord API errors;
- MongoDB query patterns and indexes;
- notification and DM behavior;
- exposure of internal details in public channels;
- dependency and workflow risk.

## Authorized Contributions

Opening an issue or pull request does not change the repository license.

Contributions may be reviewed, rejected, modified or incorporated by the
maintainer according to the license and project needs. Do not include third-party
proprietary code or material you are not allowed to provide.

