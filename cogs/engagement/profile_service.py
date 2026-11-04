"""Profile reads and bounded activity records through resilient collections."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import logging
import math

from config import MAIN_GUILD_ID
from database import (
    eco_users_col, event_col, get_db_failure_generation, guilds_col, is_db_online, msg_col,
    profiles_col, voice_col,
)
from utils import BOT_OWNER_ID, BRT, get_data_guild_id
from .profile_rules import build_profile

log = logging.getLogger(__name__)
MAX_ACTIVITY_CACHE = 10_000


async def record_event_achievements(guild, scores: dict, *, source: str):
    """Keep newly observed winners when an event closes, before later editions replace it."""
    if guild is None or guild.id != MAIN_GUILD_ID or not isinstance(scores, dict):
        return
    cleaned = {}
    for uid, score in scores.items():
        try:
            user_id, value = int(uid), float(score)
        except (ValueError, TypeError, OverflowError):
            continue
        if 0 < user_id < 2 ** 64 and math.isfinite(value) and value > 0:
            cleaned[user_id] = value
    if not cleaned:
        return
    best = max(cleaned.values())
    winners = [uid for uid, score in cleaned.items() if score == best]
    now = datetime.now(timezone.utc)
    saved = 0
    for uid in winners:
        member = guild.get_member(uid)
        if member is not None and member.bot:
            continue
        result = await asyncio.to_thread(
            profiles_col.update_one,
            {"_id": f"{guild.id}:{uid}"},
            {"$min": {"earned.campeao_de_eventos": now},
             "$setOnInsert": {"guild_id": str(guild.id), "user_id": str(uid)}},
            upsert=True,
        )
        if not result.acknowledged:
            log.warning("profile_event_awards_incomplete source=%s saved=%s winners=%s", source, saved, len(winners))
            return
        saved += 1
    log.info("profile_event_awards_saved source=%s saved=%s", source, saved)


def member_facts(member) -> dict:
    guild = member.guild
    primary = getattr(member, "primary_guild", None)
    return {
        "user_id": str(member.id), "guild_id": str(guild.id),
        "data_guild_id": str(get_data_guild_id(guild.id)),
        "main_guild_id": str(MAIN_GUILD_ID),
        "display_name": member.display_name, "username": member.name,
        "server_name": guild.name, "joined_at": member.joined_at,
        "role_ids": [role.id for role in member.roles],
        "premium_since": member.premium_since,
        "server_tag": bool(
            primary and getattr(primary, "id", None) == guild.id
            and getattr(primary, "identity_enabled", False)
        ),
        "owner_id": BOT_OWNER_ID,
    }


class ProfileService:
    def __init__(self):
        self.activity_cache = OrderedDict()
        self.activity_lock = asyncio.Lock()

    @staticmethod
    def read_profile(facts: dict, request_id: str) -> dict:
        """Called in a worker thread; never create economy records just to read."""
        key = f"{facts['guild_id']}:{facts['user_id']}"
        initial_failures = get_db_failure_generation()
        stored = profiles_col.find_one({"_id": key}) or {}
        online = is_db_online() and get_db_failure_generation() == initial_failures
        chat = voice = economy = team = None
        events = []
        if online:
            uid = facts["user_id"]
            gid = facts["data_guild_id"]
            if gid == str(MAIN_GUILD_ID):
                chat = msg_col.find_one({"_id": uid}) or {}
                voice = voice_col.find_one({"_id": uid}) or {}
                team = guilds_col.find_one({"members.user_id": {"$in": [int(uid), uid]}})
                events = [event_col.find_one({"_id": config}) or {} for config in ("config", "config2")]
            economy = eco_users_col.find_one({"_id": f"{gid}:{uid}"}) or {"guild_id": gid, "user_id": uid}
            online = is_db_online() and get_db_failure_generation() == initial_failures
        profile = build_profile(
            facts, chat_doc=chat, voice_doc=voice, economy_doc=economy,
            guild_doc=team, profile_doc=stored, event_docs=events,
            data_available=online,
        )
        profile["persistence_available"] = online
        newly = profile.get("newly_unlocked", [])
        if online and newly:
            now = datetime.now(timezone.utc)
            # $min keeps the first confirmed observation during concurrent requests.
            result = profiles_col.update_one(
                {"_id": key},
                {"$min": {f"earned.{badge}": now for badge in newly},
                 "$setOnInsert": {"guild_id": facts["guild_id"], "user_id": facts["user_id"]}},
                upsert=True,
            )
            profile["persistence_available"] = bool(result.acknowledged)
            log.log(
                logging.INFO if result.acknowledged else logging.WARNING,
                "profile_achievements_observed request_id=%s count=%s saved=%s",
                request_id, len(newly), bool(result.acknowledged),
            )
        return profile

    @staticmethod
    def save_settings(guild_id: int, user_id: int, settings: dict) -> bool:
        # Callers validate values; this allowlist prevents writing achievement facts.
        values = {key: settings[key] for key in ("bio", "theme", "featured") if key in settings}
        if not values:
            return True
        result = profiles_col.update_one(
            {"_id": f"{guild_id}:{user_id}"},
            {"$set": {**values, "updated_at": datetime.now(timezone.utc)},
             "$setOnInsert": {"guild_id": str(guild_id), "user_id": str(user_id)}},
            upsert=True,
        )
        return bool(result.acknowledged)

    async def record_activity(self, member, now: datetime | None = None):
        if not is_db_online():
            return
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(BRT).date().isoformat()
        key = f"{member.guild.id}:{member.id}"
        # One successful write per member/day; cap in memory and on disk.
        async with self.activity_lock:
            if self.activity_cache.get(key) == day:
                return
            result = await asyncio.to_thread(
                profiles_col.update_one,
                {"_id": key},
                [{"$set": {
                    "guild_id": str(member.guild.id), "user_id": str(member.id),
                    "active_days": {"$slice": [
                        {"$setUnion": [{"$ifNull": ["$active_days", []]}, [day]]}, 7,
                    ]},
                }}],
                upsert=True,
            )
            if result.acknowledged:
                self.activity_cache[key] = day
                self.activity_cache.move_to_end(key)
                while len(self.activity_cache) > MAX_ACTIVITY_CACHE:
                    self.activity_cache.popitem(last=False)
            else:
                log.debug("profile_activity_not_saved source=database")
