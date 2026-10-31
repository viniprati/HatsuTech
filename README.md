# HatsuTech

HatsuTech is a Discord bot built for the Animes Cafe community.

Current version: `1.1.0`. See [CHANGELOG.md](CHANGELOG.md)
for the version history.

The project brings together moderation, engagement, internal economy, ranks,
events, temporary roles, VIP role management, guild systems, announcements,
notifications and community tools in one bot.

## Purpose

HatsuTech helps organize and automate community operations inside Discord. Its
main areas are:

- moderation and role management;
- community engagement panels and notifications;
- chat, voice and event ranking systems;
- internal economy, inventory, shop and lootbox features;
- VIP roles, temporary roles and role recovery flows;
- internal guild/team progression systems;
- update broadcasts and user notification preferences;
- Clash Royale account and clan utilities.

## Supporter Tag Reminders

Administrators, the bot owner and members with the full-access role can run
`/tag` in the main server to scan all members and send the HatsuTech introduction
and Apoiador claim link to people displaying the
server tag without the Apoiador role. Bots and hidden tags are excluded; each
recipient is checked again before delivery. The command does not grant roles.

The command runs at most once per hour per server, prevents overlapping runs,
and spaces delivery attempts by 1.25 seconds. Successful and closed-DM attempts
are recorded in the existing `welcome_dm_logs` collection with type
`tag_supporter_reminder` and are skipped on later runs. Each DM is reserved
atomically before sending. If delivery or its final record is uncertain, its
`pending` reservation is preserved for manual review and is not sent again
automatically. Definite rejections can be retried on a later run. Sending stops
if history cannot be confirmed or Discord returns a rate limit or repeated
failures.

The administrator receives private progress and delivery counts. Runs exceeding
Discord's interaction lifetime may lose the private report; the final counts
remain in the `tag_reminders_finished` log, correlated by `run_id`.
MongoDB and Discord's Server Members intent must be available. The existing
Apoiador role and claim panel channel must exist and be accessible to members.
After deploying, use `!sync` in the main server to register `/tag`. Authorization
is checked by the bot using the shared owner/full-access bypass; Discord's
default command permissions must not require Administrator, which would hide
the command from the bot owner when they lack that server permission.

## Repository Access

This repository is public for reading, review and transparency. Public
visibility does not grant permission to use, copy, host, modify, redistribute or
create derivative works from the bot.

For review guidance, see:

- [Repository Review](docs/REPOSITORY_REVIEW.md)
- [AI Development Workflow](docs/AI_DEVELOPMENT_WORKFLOW.md)
- [Security Policy](SECURITY.md)

## Service Documents

The official HatsuTech service is governed by:

- Terms of Service: https://viniprati.github.io/Hatsutech-Termos-de-Uso/
- Privacy Policy: https://viniprati.github.io/Hatsutech-Politica-de-Privacidade/

## License

This repository is source-available for reading and review only.

It is not released under an open-source license. Use, copying, modification,
hosting, redistribution or derivative works require prior written authorization
from the copyright holder.

See [LICENSE](LICENSE) for the complete terms.
