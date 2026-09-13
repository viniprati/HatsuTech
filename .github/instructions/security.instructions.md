---
applyTo: "**/*"
---

# Security Review Instructions

HatsuTech handles Discord user IDs, guild IDs, role IDs, economy records, VIP
records, moderation utilities and operational logs. Treat authorization and
data exposure as high-priority review areas.

Check for:

- secrets, tokens, API keys, cookies or database URIs committed to the repo;
- unsafe use of `.env` or production credentials;
- missing permission checks on admin, economy, VIP or moderation commands;
- role hierarchy mistakes that let users modify protected roles;
- user-controlled content inserted into embeds without context or limits;
- public error messages exposing stack traces, internal IDs or operational
  details;
- mass notification behavior that could violate Discord rules;
- missing audit trail for balance, role, VIP or moderation changes;
- third-party API failures that are not handled;
- logs that store unnecessary personal data;
- unbounded database queries or reports.

Do not disclose critical vulnerabilities in public issues. Use GitHub private
security reporting or contact the maintainer privately.

