---
applyTo: "**/*.py"
---

# Python Discord Bot Instructions

This repository is a Python Discord bot built with `discord.py`.

Prefer the existing cog and command structure. Keep new code in the domain that
owns the behavior:

- updates and announcements in `cogs/atualizacoes`;
- Clash Royale integrations in `cogs/clashroyale`;
- economy features in `cogs/economia`;
- engagement, supporter and play-call features in `cogs/engagement`;
- guild progression in `cogs/guilda`;
- moderation in `cogs/moderation`;
- chat, voice and event ranks in `cogs/ranks`;
- VIP and temporary role flows in `cogs/vip`.

Guidelines:

- Use existing helper functions before adding new abstractions.
- Keep slash commands small and delegate domain logic when the file is already
  split into command modules.
- Validate `guild`, `channel`, `role`, `member` and `user` objects before use.
- Handle common Discord API exceptions explicitly.
- Use `allowed_mentions` intentionally when sending messages.
- Avoid public responses for admin-only diagnostics.
- Avoid mass DM behavior unless there is a clear product reason and safe pacing.
- Use `asyncio.to_thread` for blocking PyMongo operations when called from async
  command handlers.
- Keep database logs structured and small.
- Do not introduce secrets or environment-specific values into code.
- Run compile checks before considering a change complete.

