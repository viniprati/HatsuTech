# Guild treasury

## Rules

- `/guilda criar` charges the creator 4,000 Essências once. Validation, debit,
  creation and fee history commit together. Failed creation leaves no debit.
- Existing guilds start with zero treasury balance and are not charged a fee.
- The existing monthly thresholds remain: 50k/60k/75k/90k/100k XP yield
  5%/10%/15%/20%/25% extra Éter, respectively.
- Chat and voice eligibility rules remain the same. Personal base earnings
  and VIP bonuses stay personal; only the extra guild bonus enters the treasury.
  A successfully credited activity still awards one guild XP regardless of
  currency multipliers or bonuses.
- Fractions of guild bonus accumulate per member in integer hundredths inside
  the guild membership record until a whole Éter can enter the treasury. Leaving
  the guild removes that record, including an uncompleted fraction and personal
  contribution counters; whole Éter already deposited stays in the treasury.
- Old personal `stats.guild_bonus_remainder` values are not paid again or moved
  to a guild: those historical fractions have no reliable guild attribution.
- Treasury balance persists across weeks/months. The monthly percentage resets
  with the season; the accumulated treasury does not.
- `/guilda distribuir` is leader-only. All members confirmed present in Discord,
  excluding bots, with at least seven full days since their current `joined_at`
  receive the same integer amount. The leader follows the same eligibility rule.
  Missing join dates are insufficient evidence of eligibility. Existing naive
  MongoDB join dates are interpreted as UTC, consistent with database timestamps.
- A Discord member lookup failure stops payment; a confirmed `NotFound` excludes
  the departed member. Membership changes during preparation cancel the request.
  Activity increments do not cancel it.
- The leader cannot select recipients, individual amounts or a personal withdrawal.
  A member who leaves and rejoins starts a new seven-day waiting period.
- Integer division remainders stay in the treasury. A balance smaller than the
  number of eligible recipients cannot be distributed yet; wait for further
  earnings or a change in eligible membership. There is no unequal final payout.
- Both leader and administrative deletion refuse a guild with any whole Éter
  left in its treasury. This also applies to division remainders.
- Leaving/kicking a member does not subtract XP or whole Éter previously earned.
- The bot also removes guild memberships when Discord confirms someone left the
  main server. It checks on departure events, on startup and hourly to catch
  older records. A failed lookup leaves the membership for a later check.
- When the leader leaves, the oldest remaining member confirmed present takes
  over. If there are unverified candidates and nobody confirmed present, the
  transfer waits for a later check. Empty guilds keep their record, XP and
  treasury for administrative handling, with no assigned leader.

## Extra member slots

Guild leaders can use `/guilda vagas` to add one member slot at a time. The
first slot costs 2,000 Essências. Each slot already purchased raises the next
price by 500 Essências. The base guild capacity is 10.

Members contribute from their own wallets using `/guilda doar_essencias`.
The bot spends the guild's Essence reserve first and charges the leader's
wallet for the remainder. The confirmation shows the maximum personal debit.
If the combined funds are insufficient, the purchase leaves both balances
unchanged. `/guilda_cofre` shows the reserve privately and `/historico_guilda`
records donations and purchases. Donations are final and the reserve can only
fund slot purchases. Deleting the guild discards slots and remaining donated
Essências without refunds. The Éter treasury follows its own rules.

Owners of active personal VIP roles can use `/vip_vagas` to add one member
slot at a time. The first slot costs 1,000 Essências and each purchased slot
raises the next price by 250 Essências. Upgrades apply only to the purchased
role ID. A role recreated from a preset starts at the base VIP limit. The
new commands require `!sync` after deployment.

## History and privacy

`/guilda_cofre` shows the treasury total and the requesting member's contribution
in an ephemeral response. It has no arbitrary guild selector: only current
members can consult their own guild's treasury. Both successful replies and
errors remain private. The public `/guilda painel` contains activity/XP only,
without treasury balances or financial contribution amounts.

`/historico_guilda` has no arbitrary guild selector. Any current member can open
the history of their own guild in an ephemeral response. It shows the latest
100 financial movements, five per page. Each navigation revalidates both the
requesting user and current guild membership; leaving or expulsion disables
further access. A recipient can still retain information they already viewed.

Creation fees and distributions have individual records. Whole-Éter deposits
are grouped by guild/member/Brasília date/source (chat or voice); the date shown
is the last update of that aggregate. Distribution history includes the leader,
total, recipients, per-member amount and remainder. Historical operations before
this deployment are not reconstructed. Names/message bodies are not stored.

The `guild_history` collection retains financial records. Queries are bounded
and indexed by guild and update time. Temporary activity receipts live in
`guild_reward_receipts`, with a seven-day TTL index to prevent gateway/task
replays from duplicating a recent activity reward. Creation and distribution
receipts remain in history and use the Discord interaction ID for idempotency.

## Deployment

1. Deploy to a MongoDB replica set or sharded cluster supporting transactions
   (Atlas supports this). Financial paths use the existing shared client and
   resilient collection wrappers with session-bound errors propagated to abort
   the transaction. No additional client or dependency is introduced in bot code.
2. The MongoDB account must be allowed to transact, write the two new collections
   and create their indexes. Verify startup index initialization succeeds.
3. Run `!sync` in each authorized server to register `/guilda_cofre`, `/guilda distribuir` and
   `/historico_guilda` and update the creation-command description.
4. Existing documents need no bulk migration. Treasury fields initialize lazily.

Transactions use snapshot reads and majority writes. Personal activity credits,
VIP fractions, treasury deposits, XP and deposit history commit together.
Distribution credits every recipient, deducts the treasury and records history
in one commit. A failed or unsupported transaction produces no partial payout;
an uncertain result is reported as unconfirmed rather than refunded or repeated
with a new identity. Retrying the same operation ID is safe. A new command after
an uncertain result should first inspect the guild panel/history.

If transactions are unavailable, activity rewards also stop; there is no fallback
that could credit one side of the personal/guild accounting. Other nonfinancial
features retain the existing degraded behavior. Monitor the
`mongodb_transaction_failed` and `activity_reward_not_confirmed` logs.

The authorized test server continues using the main server's canonical economy
wallets and guild records. Its distributions and creation fees affect those
same balances; use a separate local database for financial tests.

## Tests

Baseline commands are listed in `AGENTS.md`. Unit tests cover transaction error
propagation, private history, membership revalidation and uncertain Discord
lookups. The integration suite additionally covers real MongoDB rollback,
concurrent creation/rewards/distribution, fractions, seven-day eligibility,
month rollover, canonical wallet mapping and money conservation.

Integration tests require an explicitly supplied **local** replica set URI:

```bash
HATSUTECH_TEST_MONGO_URI='mongodb://127.0.0.1:27019/?replicaSet=hatsutech-test' \
  python -m unittest discover -s tests -p 'test_guild_finance_integration.py' -v
```

Only loopback hosts are accepted. The suite creates and drops a randomly named
`hatsutech_guild_tests_*` database. It does not use the bot's `.env` credentials
or `DiscordBotDB`. Alternatively set `HATSUTECH_TEST_MONGO_PORT=27019` for the
local replica named `hatsutech-test`, as CI does. Without an explicit test URI
or port, integration tests are skipped.
