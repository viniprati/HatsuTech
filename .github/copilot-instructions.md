# Copilot Code Review Instructions

Review HatsuTech as a production Discord bot, not as a generic Python sample.
Use `AGENTS.md` as the primary engineering contract.

Prioritize comments in this order:

1. Real bugs
2. Security issues
3. Authentication and authorization issues
4. Input validation problems
5. Regressions in existing bot behavior
6. Concurrency, rate limit and retry problems
7. Relevant performance issues
8. Error handling gaps
9. Architecture or ownership boundary concerns
10. Missing tests or missing validation commands
11. Maintainability concerns

Avoid noisy comments about style if the issue can be handled by an automated
formatter or linter. Do not request rewrites that do not materially improve
correctness, security, reliability or maintainability.

When reviewing Discord bot code, check:

- command permission checks;
- privileged role and owner checks;
- Discord role hierarchy constraints;
- `discord.Forbidden`, `discord.NotFound` and `discord.HTTPException` handling;
- rate limit behavior;
- `allowed_mentions` usage;
- DM broadcast risk and opt-out behavior;
- accidental public exposure of private admin data;
- embeds that include untrusted user input;
- background task failure handling.

When reviewing MongoDB code, check:

- use of the resilient database wrappers;
- indexes for new query patterns;
- bounded logs and reports;
- safe behavior when the database is unavailable;
- consistent Discord ID storage types.

When reviewing economy, VIP or staff tooling, check:

- balance manipulation cannot be used without permission;
- every manual balance adjustment has an audit trail and reason;
- VIP ownership cannot be hijacked through role IDs;
- staff-only actions do not leak to public channels;
- destructive or irreversible actions require confirmation where appropriate.

Suggest code only when it is necessary to explain the fix. Explain the reason
for each suggestion.

