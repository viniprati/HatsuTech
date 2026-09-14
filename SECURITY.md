# Security Policy

HatsuTech is a source-available Discord bot used by the Animes Cafe community.
Security reports should protect users, staff operations and private
infrastructure details.

## Reporting A Vulnerability

Do not open a public issue for critical or sensitive vulnerabilities.

Use one of these private channels:

- GitHub private vulnerability reporting, when available:
  https://github.com/viniprati/HatsuTech/security/advisories/new
- Email: prativinicius@gmail.com
- Discord: https://discord.com/users/983870132063453235

Please include:

- affected command, cog, workflow or configuration;
- impact and abuse scenario;
- reproduction steps, if safe to share privately;
- relevant logs or screenshots with secrets removed;
- suggested fix, if known.

## Scope

Relevant areas include:

- Discord bot tokens, API keys and environment variables;
- command authorization and staff permission checks;
- economy balance changes and reward flows;
- VIP ownership, role recovery and temporary roles;
- moderation commands and role hierarchy handling;
- MongoDB access, indexes and operational logs;
- DM, announcement and notification behavior;
- GitHub Actions and deployment configuration.

## Out Of Scope

The following are usually not treated as security vulnerabilities unless they
can be chained into a real impact:

- style-only issues;
- missing comments or formatting differences;
- dependency updates without an exploitable path;
- reports requiring access to private credentials you do not own;
- denial-of-service tests against the production bot or community server.

## Safe Handling

Do not publish:

- Discord tokens;
- MongoDB URIs;
- Clash Royale API keys;
- private `.env` values;
- private user data;
- exploit steps that allow abuse before a fix exists.

The maintainer may request additional information, open a private advisory,
prepare a patch and publish a public summary after the issue is resolved.

