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

## VIP Owner Departure

When a VIP role owner leaves or is banned, the bot deletes their linked personal
role and Monarch highlight after confirming they are no longer in the server.
Base VIP roles, managed roles and roles linked to another owner are preserved.
Failed deletions keep their database links for retry by the existing ten-minute
reconciliation task, with a one-hour delay after failures. The task also processes
older records marked for review.

Every personal-role/highlight deletion completed by the bot sends an administrative
DM report through the existing audit helper. This includes departure/ban cleanup,
inactivity, loss of VIP eligibility and owner-panel deletion. Reports identify the
owner, role, reason and source, and only confirm the Discord deletion; database
updates follow in the responsible flow. Missing roles or failed deletions do not
produce success reports, and DM failures do not interrupt cleanup. Recipients are
configured through `ADMIN_AUDIT_DM_USER_IDS`, defaulting to PRATI
(`983870132063453235`) and Renk (`459064218088374293`). No new slash-command sync is
required for this behavior; deploy the updated code and allow DMs to both users.

## VIP Inactivity

Personal VIP roles created through `/vip` or linked through `/vincular_vip`, and
Monarch highlights, are deleted after ten days without observed owner activity.
Messages in any visible server channel or thread, reactions, commands, buttons,
modal submissions and voice activity outside the AFK channel renew the window.
Being online alone does not count. Ongoing voice presence also prevents deletion.
Only activity timestamps are recorded; message content is not stored for this feature.

The check runs every ten minutes and preserves base VIP roles and roles linked
to another owner. Missing history or a monitoring gap longer than thirty minutes
starts a new ten-day window instead of assuming inactivity during the gap.
Existing records also receive a new window when this activity policy is first
applied, because older tracking did not cover all these activity types.

### Local Message History Report

To inspect messages that already exist from the last ten days in the configured
lobby (`CHAT_COUNT_CHANNEL_ID`), run:

```bash
python scripts/audit_vip_message_history.py --days 10
```

Configure `DISCORD_TOKEN` and `MONGO_URI` in the root `.env`. The token is used
only for Discord REST reads; this script does not start the bot, connect a second
gateway session, load cogs, send messages or alter roles/database documents.
Use `--guild-id SERVER_ID` for another server. `--input BACKUP.json` supplies the
VIP ownership records from a local backup instead of MongoDB, while still reading
message history from Discord.

By default, only the lobby's own messages are scanned. Use `--channel-id CHANNEL_ID`
to select a different channel, `--include-threads` to include that channel's threads,
or `--all-channels` to scan the whole server and its accessible active/archived
threads. The selected scope is recorded in the JSON. The script reads the whole
requested interval without a per-channel message cap. Large histories can take
time; requests use discord.py's rate-limit handling. The
bot needs View Channel and Read Message History; Manage Threads improves coverage
of private archives. Missing permissions or failed requests are recorded as
partial coverage rather than proof of inactivity.

Each run writes a dated JSON in `scripts/output/vip_message_history/`, already
ignored by Git. It contains owner/role IDs and names, counts, latest-message dates
and links, and channel coverage. Message bodies and credentials are not exported.
Deleted messages/channels and past calls, reactions or interactions cannot be
reconstructed by this scan. No messages found does not prove general inactivity.

### Stored Activity Report

Run the read-only audit from the repository root with the existing dependencies
installed and `MONGO_URI` in `.env`. No Discord token is required; the bot is not
started and the audit does not change documents, indexes or roles.

```bash
python scripts/audit_vip_activity.py
python scripts/audit_vip_activity.py --days 10 --csv scripts/output/vip_activity.csv
```

Each successful run automatically creates a dated JSON snapshot under
`scripts/output/vip_activity/`, regardless of the current working directory.
This directory is covered by `.gitignore`. Snapshots include the report, summary,
selected activity fields and export time; credentials are not included. Earlier
snapshots are preserved and can be reused with `--input` for local analysis.

Use `--guild-id SERVER_ID` for another server, or `--input backups/vip_roles/FILE.json`
to inspect a JSON backup offline. `--include-legacy` includes records without a
confirmed server, explicitly marked as insufficient history.

The report identifies each owner and registered role by ID, shows the latest
recorded activity in Brasília time and distinguishes recent activity, no activity
recorded under the current monitoring policy, possible inactivity with incomplete
history, and missing dates. It does not reconstruct past activity or verify that
the registered role still exists on Discord. Possible inactivity requires review.

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
