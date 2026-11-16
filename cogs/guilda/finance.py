"""Atomic guild fees, activity rewards and equal treasury distributions.

All callbacks are DB-only because PyMongo may retry a transaction. Discord
membership is resolved by the command before distribution and checked against
the stored membership snapshot again inside the transaction.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson import ObjectId

from config import MAIN_GUILD_ID
from database import eco_users_col, guild_history_col, guild_reward_receipts_col, guilds_col, run_transaction
from utils import BRT, get_data_guild_id

CREATION_FEE = 4_000
MIN_MEMBERSHIP_DAYS = 7
HISTORY_LIMIT = 100


class GuildFinanceError(ValueError):
    pass


def utc_date(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def member_ids(document):
    return [int(record["user_id"]) for record in document.get("members", [])]


def membership_signature(records):
    # BSON dates have millisecond precision; compare the stored representation.
    signature = []
    for record in records:
        joined = utc_date(record.get("joined_at"))
        signature.append((int(record["user_id"]), joined.isoformat(timespec="milliseconds") if joined else ""))
    return sorted(signature)


def check_scope(document, server_id):
    canonical = get_data_guild_id(server_id)
    if int(document.get("server_id", MAIN_GUILD_ID)) != canonical:
        raise GuildFinanceError("Esta guilda pertence a outro servidor.")


def economy_id(server_id, user_id):
    return f"{get_data_guild_id(server_id)}:{user_id}"


def _record(session, operation_id, guild_id, kind, now, **details):
    guild_history_col.insert_one({
        "_id": operation_id, "guild_id": guild_id, "type": kind,
        "created_at": now, "updated_at": now, **details,
    }, session=session)


def _membership_lock(session):
    # Serializes the low-volume join/create/name checks, including legacy data
    # that cannot safely receive unique indexes without a migration audit.
    guild_history_col.update_one(
        {"_id": "membership_lock"}, {"$inc": {"version": 1}}, upsert=True, session=session,
    )


def create_guild(server_id, actor_id, name, emoji, operation_id):
    now, guild_id = datetime.now(timezone.utc), ObjectId()
    name, emoji = name.strip(), emoji.strip()
    if not name or len(name) > 20 or not emoji or len(emoji) > 50:
        raise GuildFinanceError("Informe nome de até 20 caracteres e emoji de até 50 caracteres.")

    def execute(session):
        previous = guild_history_col.find_one({"_id": operation_id}, session=session)
        if previous:
            return previous["guild_id"]
        _membership_lock(session)
        if guilds_col.find_one({"members.user_id": {"$in": [actor_id, str(actor_id)]}}, session=session):
            raise GuildFinanceError("Você já está em uma guilda.")
        if guilds_col.find_one({"name": name}, session=session):
            raise GuildFinanceError("Já existe uma guilda com esse nome.")
        charged = eco_users_col.update_one(
            {"_id": economy_id(server_id, actor_id), "essencia": {"$gte": CREATION_FEE}},
            {"$inc": {"essencia": -CREATION_FEE}, "$set": {"updated_at": now}}, session=session,
        )
        if not charged.matched_count:
            raise GuildFinanceError("Você precisa de 4.000 Essências para criar uma guilda.")
        guilds_col.insert_one({
            "_id": guild_id, "server_id": str(get_data_guild_id(server_id)),
            "name": name, "emoji": emoji, "leader_id": actor_id, "created_at": now,
            "total_xp": 0, "treasury_eter": 0, "treasury_total_earned": 0,
            "members": [{"user_id": actor_id, "joined_at": now, "xp": 0,
                         "msg_count": 0, "voice_seconds": 0, "message_xp": 0, "voice_xp": 0}],
        }, session=session)
        _record(session, operation_id, guild_id, "creation", now, actor_id=str(actor_id), fee=CREATION_FEE)
        return guild_id

    return run_transaction(execute)


def join_guild(server_id, guild_id, user_id, expected_members, active_ids):
    now = datetime.now(timezone.utc)

    def execute(session):
        _membership_lock(session)
        document = guilds_col.find_one({"_id": guild_id}, session=session)
        if not document:
            raise GuildFinanceError("Esta guilda não existe mais.")
        check_scope(document, server_id)
        if membership_signature(document.get("members", [])) != membership_signature(expected_members):
            raise GuildFinanceError("Os membros mudaram. Peça um novo convite.")
        if len(set(member_ids(document)) & set(active_ids)) >= 10:
            raise GuildFinanceError("A guilda já tem dez membros presentes no servidor.")
        if guilds_col.find_one({"members.user_id": {"$in": [user_id, str(user_id)]}}, session=session):
            raise GuildFinanceError("Você já está em uma guilda.")
        guilds_col.update_one({"_id": guild_id}, {"$push": {"members": {
            "user_id": user_id, "joined_at": now, "xp": 0, "msg_count": 0,
            "voice_seconds": 0, "message_xp": 0, "voice_xp": 0,
        }}}, session=session)

    run_transaction(execute)


def credit_activity(cog, server_id, user_id, source, base_gain, vip_percent, operation_id):
    """Credit personal base/VIP, treasury bonus and guild XP in one commit."""
    now = datetime.now(timezone.utc)
    if source not in {"message", "voice"} or base_gain <= 0:
        raise ValueError("Invalid activity reward")

    def execute(session):
        user_key = economy_id(server_id, user_id)
        receipt_id = f"{user_key}:{source}:{operation_id}"
        if guild_reward_receipts_col.find_one({"_id": receipt_id}, session=session):
            return False
        guild_reward_receipts_col.insert_one({"_id": receipt_id, "created_at": now}, session=session)
        user = eco_users_col.find_one({"_id": user_key}, session=session) or {}
        doc = guilds_col.find_one({"members.user_id": {"$in": [user_id, str(user_id)]}}, session=session)
        if doc:
            check_scope(doc, server_id)
            if cog is None:
                raise GuildFinanceError("O sistema de guildas está temporariamente indisponível.")
        remainder = (user.get("stats") or {}).get("vip_bonus_remainder", {}).get("eter", 0)
        raw = Decimal(str(remainder)) + Decimal(base_gain * vip_percent) / 100
        vip_extra = int(raw)
        delivered = base_gain + vip_extra
        eco_users_col.update_one({"_id": user_key}, {
            "$inc": {"eter": delivered, f"stats.earned_{'chat' if source == 'message' else 'voice'}": delivered},
            "$set": {"updated_at": now,
                     "stats.vip_bonus_remainder.eter": float(raw - vip_extra)},
            "$setOnInsert": {"user_id": str(user_id), "guild_id": str(get_data_guild_id(server_id))},
        }, upsert=True, session=session)
        if not doc:
            return True
        percent = cog.monthly_boost_percent(cog.monthly_xp(doc))
        record = next(r for r in doc["members"] if int(r["user_id"]) == user_id)
        extra, leftover = divmod(int(record.get("treasury_remainder", 0)) + base_gain * percent, 100)
        resets = cog._reset_period_stats_if_needed(doc)
        if resets:
            guilds_col.update_one({"_id": doc["_id"]}, {"$set": resets}, session=session)
        counters = {"members.$.message_xp": 1, "members.$.msg_count": 1} if source == "message" else {
            "members.$.voice_xp": 1, "members.$.voice_seconds": 10,
        }
        update = cog._build_guild_xp_update(doc, source, 1, counters)
        update["$inc"].update({"treasury_eter": extra, "treasury_total_earned": extra,
                               "members.$.treasury_contributed": extra})
        update["$set"] = {"members.$.treasury_remainder": leftover}
        guilds_col.update_one({"_id": doc["_id"], "members.user_id": record["user_id"]}, update, session=session)
        if extra:
            day = now.astimezone(BRT).date().isoformat()
            guild_history_col.update_one({"_id": f"deposit:{doc['_id']}:{user_id}:{day}:{source}"}, {
                "$inc": {"amount": extra}, "$set": {"updated_at": now},
                "$setOnInsert": {"guild_id": doc["_id"], "type": "deposit", "created_at": now,
                                 "actor_id": str(user_id), "source": source},
            }, upsert=True, session=session)
        return True

    return run_transaction(execute)


def distribute(server_id, guild_id, actor_id, expected_members, active_ids, operation_id, *, now=None):
    now = now or datetime.now(timezone.utc)

    def execute(session):
        document = guilds_col.find_one({"_id": guild_id}, session=session)
        if not document:
            raise GuildFinanceError("Esta guilda não existe mais.")
        check_scope(document, server_id)
        if int(document["leader_id"]) != actor_id:
            raise GuildFinanceError("Somente o líder pode distribuir o cofre.")
        if actor_id not in member_ids(document):
            raise GuildFinanceError("O líder precisa fazer parte da guilda.")
        previous = guild_history_col.find_one({"_id": operation_id}, session=session)
        if previous:
            return previous
        if membership_signature(document.get("members", [])) != membership_signature(expected_members):
            raise GuildFinanceError("Os membros mudaram. Execute a distribuição novamente.")
        eligible = set()
        for record in document.get("members", []):
            joined = utc_date(record.get("joined_at"))
            if int(record["user_id"]) in active_ids and joined and joined <= now - timedelta(days=MIN_MEMBERSHIP_DAYS):
                eligible.add(int(record["user_id"]))
        if not eligible:
            raise GuildFinanceError("Nenhum membro presente completou sete dias na guilda.")
        balance = int(document.get("treasury_eter", 0))
        share, remainder = divmod(balance, len(eligible))
        if share <= 0:
            raise GuildFinanceError("O cofre precisa ter pelo menos um Éter por membro elegível.")
        for uid in sorted(eligible):
            eco_users_col.update_one({"_id": economy_id(server_id, uid)}, {
                "$inc": {"eter": share, "stats.guild_distributions_received": share},
                "$set": {"updated_at": now},
                "$setOnInsert": {"user_id": str(uid), "guild_id": str(get_data_guild_id(server_id))},
            }, upsert=True, session=session)
        guilds_col.update_one({"_id": guild_id}, {"$inc": {"treasury_eter": -share * len(eligible)}}, session=session)
        result = {"actor_id": str(actor_id), "amount": share * len(eligible), "share": share,
                  "recipients": [str(uid) for uid in sorted(eligible)], "remainder": remainder}
        _record(session, operation_id, guild_id, "distribution", now, **result)
        return result

    return run_transaction(execute)


def read_history(server_id, user_id, guild_id):
    def execute(session):
        document = guilds_col.find_one({"_id": guild_id, "members.user_id": {"$in": [user_id, str(user_id)]}}, session=session)
        if not document:
            raise GuildFinanceError("Você só pode consultar o histórico da sua guilda atual.")
        check_scope(document, server_id)
        entries = list(guild_history_col.find({"guild_id": guild_id}, session=session)
                       .sort([("updated_at", -1), ("_id", -1)]).limit(HISTORY_LIMIT))
        return document, entries

    return run_transaction(execute)


def read_current_guild(server_id, user_id):
    def execute(session):
        document = guilds_col.find_one({"members.user_id": {"$in": [user_id, str(user_id)]}}, session=session)
        if not document:
            raise GuildFinanceError("Você não está em uma guilda.")
        check_scope(document, server_id)
        return document

    return run_transaction(execute)


def delete_guild(server_id, guild_id, actor_id, operation_id, *, admin=False):
    def execute(session):
        document = guilds_col.find_one({"_id": guild_id}, session=session)
        if not document:
            return False
        check_scope(document, server_id)
        if not admin and int(document["leader_id"]) != actor_id:
            raise GuildFinanceError("Somente o líder pode excluir a guilda.")
        if int(document.get("treasury_eter", 0)) > 0:
            raise GuildFinanceError("Distribua todo o saldo do cofre antes de excluir a guilda. Sobras também precisam ser distribuídas.")
        guilds_col.delete_one({"_id": guild_id}, session=session)
        _record(session, operation_id, guild_id, "deletion", datetime.now(timezone.utc), actor_id=str(actor_id))
        return True

    return run_transaction(execute)
