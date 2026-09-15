# Maintenance Review

## Scope

This review covers the maintenance batch for command reliability, Discord API
limits, background tasks, configuration validation, database resilience,
Clash Royale API failures, update DMs and operational logging.

## Findings Addressed

- Startup, command errors and MongoDB status used console prints in production
  paths, making failures harder to correlate after deployment.
- Announcement DMs accepted unbounded title/body input and did not validate
  attachment type before using it as an embed image.
- Welcome DMs could be sent again to members who had already received or
  blocked the welcome message.
- Subscriber notification reads and writes were synchronous inside async
  command execution.
- Several background tasks started unconditionally from cog constructors and
  had no explicit task error handler.
- Some dynamic embeds could exceed Discord limits when lists grow.
- Clash Royale API errors were user-visible, but lacked enough structured log
  context for later diagnosis.
- Admin statistics assumed every cached member has `joined_at`, which can be
  absent in partial cache states.

## Validation

- `python -m compileall -q main.py config.py database.py utils.py cogs scripts`
- `python scripts/validate_static_contracts.py`
- `git diff --check`
- `python -m pip check`

## Review Notes

- No secrets or environment-specific credentials were added.
- The new static validator is intentionally offline and does not require a bot
  token, MongoDB URI or Clash Royale API token.
- Source-available licensing remains unchanged; this document is a maintenance
  review, not a public operation guide.
