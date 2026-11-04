"""Pure profile and achievement rules.

This module deliberately has no Discord or database imports.  Callers collect
the facts they are allowed to expose and pass them here; missing facts remain
unknown instead of being converted into zeroes or fabricated achievements.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

MAIN_GUILD_ID = "609159041499004982"
SUPPORTER_ROLE_ID = 1512225314502086746
VIP_ROLE_LABELS = {
    999723165225857074: "VIP Berserk",
    1121511055059861524: "VIP Mugetsu",
    1351596017631494195: "VIP Monarch",
}

ACHIEVEMENTS = (
    ("lenda_do_cafe", "Lenda do Café", "365 dias no servidor", 365.0, "days"),
    ("cafeinado", "Cafeinado", "10.000 pontos de chat", 10_000.0, "chat"),
    ("voz_do_cafe", "Voz do Café", "100 horas no ranking de voz (inclui bônus)", 100.0, "voice_hours"),
    ("criador_da_hatsu", "Criador da Hatsu", "Participação no desenvolvimento", 1.0, "owner"),
    ("maratonista", "Maratonista", "1.000 horas no ranking de voz (inclui bônus)", 1_000.0, "voice_hours"),
    ("primeiro_gole", "Primeiro Gole", "Primeira participação registrada", 1.0, "participation"),
    ("presenca_marcante", "Presença Marcante", "Atividade em 7 dias diferentes", 7.0, "active_days"),
    ("alma_da_guilda", "Alma da Guilda", "1.000 XP na guilda", 1_000.0, "guild_xp"),
    ("campeao_de_eventos", "Campeão de Eventos", "Vencer um evento", 1.0, "event_win"),
    ("apoiador_do_cafe", "Apoiador do Café", "Apoiador atual do servidor", 1.0, "supporter"),
)
ACHIEVEMENT_IDS = tuple(item[0] for item in ACHIEVEMENTS)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _finite(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        value = fallback
    value = _CONTROL.sub("", str(value)).strip()
    return value or fallback


def _safe_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _doc_belongs(doc: Any, data_guild_id: str, *, allow_legacy: bool = True) -> bool:
    if not isinstance(doc, dict):
        return False
    explicit = doc.get("guild_id")
    return (explicit is None and allow_legacy) or str(explicit) == str(data_guild_id)


def _user_matches(doc: Any, user_id: str) -> bool:
    if not isinstance(doc, dict):
        return False
    if "user_id" in doc and str(doc["user_id"]) != user_id:
        return False
    return "_id" not in doc or str(doc["_id"]).split(":")[-1] == user_id


def _earned(profile_doc: Any, achievement_id: str) -> bool:
    if not isinstance(profile_doc, dict) or not isinstance(profile_doc.get("earned"), dict):
        return False
    value = profile_doc["earned"].get(achievement_id)
    if isinstance(value, datetime):
        return True
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    return False


def _member_xp(guild_doc: Any, user_id: str) -> float | None:
    if not isinstance(guild_doc, dict):
        return None
    members = guild_doc.get("members")
    if not isinstance(members, list):
        return None
    for member in members:
        if not isinstance(member, dict) or str(member.get("user_id")) != str(user_id):
            continue
        return _finite(member.get("xp"))
    return None


def _event_win(event_docs: Any, user_id: str, *, is_main: bool, main_guild_id: str) -> bool | None:
    found = False
    for doc in event_docs or ():
        if not isinstance(doc, dict):
            continue
        explicit_guild = doc.get("guild_id")
        if explicit_guild is not None and str(explicit_guild) != main_guild_id:
            continue
        if explicit_guild is None and not is_main:
            continue
        scores = doc.get("last_event_scores")
        if not isinstance(scores, dict) or not scores:
            continue
        clean = {str(k): _finite(v) for k, v in scores.items()}
        clean = {k: v for k, v in clean.items() if v is not None and v > 0}
        if not clean:
            continue
        found = True
        best = max(clean.values())
        if clean.get(str(user_id)) == best:
            return True
    return False if found else None


def build_profile(
    facts: dict,
    *,
    chat_doc: dict | None = None,
    voice_doc: dict | None = None,
    economy_doc: dict | None = None,
    guild_doc: dict | None = None,
    profile_doc: dict | None = None,
    event_docs=(),
    data_available: bool = True,
    now: datetime | None = None,
) -> dict:
    """Build a safe renderer payload from already-authorized facts."""
    now_utc = _safe_datetime(now) or datetime.now(timezone.utc)
    user_id = str(facts.get("user_id", ""))
    main_guild_id = str(facts.get("main_guild_id") or MAIN_GUILD_ID)
    data_guild_id = str(facts.get("data_guild_id") or facts.get("guild_id") or "")
    real_guild_id = str(facts.get("guild_id", data_guild_id))
    is_main = data_guild_id == main_guild_id
    db_ok = bool(data_available)
    if not isinstance(profile_doc, dict) or not _doc_belongs(profile_doc, real_guild_id) or not _user_matches(profile_doc, user_id):
        profile_doc = {}

    # Chat/voice counters are legacy global records. They are trusted only for
    # the canonical main guild, never for an arbitrary test/foreign guild.
    chat_valid = db_ok and is_main and _doc_belongs(chat_doc, data_guild_id) and _user_matches(chat_doc, user_id)
    voice_valid = db_ok and is_main and _doc_belongs(voice_doc, data_guild_id) and _user_matches(voice_doc, user_id)
    economy_valid = db_ok and _doc_belongs(economy_doc, data_guild_id, allow_legacy=is_main) and _user_matches(economy_doc, user_id)
    guild_valid = db_ok and is_main and _doc_belongs(guild_doc, data_guild_id)
    chat = _finite(chat_doc.get("count", 0)) if chat_valid else None
    voice_seconds = _finite(voice_doc.get("time", 0)) if voice_valid else None
    voice_hours = voice_seconds / 3600 if voice_seconds is not None else None
    eter = _finite(economy_doc.get("eter", 0)) if economy_valid else None
    essencia = _finite(economy_doc.get("essencia", 0)) if economy_valid else None

    joined = _safe_datetime(facts.get("joined_at"))
    days = max(0.0, (now_utc - joined).total_seconds() / 86400) if joined else None
    role_ids = {int(x) for x in (facts.get("role_ids") or ()) if str(x).isdigit()}
    active_days = profile_doc.get("active_days", []) if db_ok else None
    valid_days = set()
    if isinstance(active_days, list):
        for value in active_days[:7]:
            if not isinstance(value, str):
                continue
            try:
                parsed = date.fromisoformat(value)
                if parsed <= now_utc.date():
                    valid_days.add(parsed.isoformat())
            except ValueError:
                continue
    active_count = len(valid_days) if isinstance(active_days, list) else None
    guild_xp = _member_xp(guild_doc, user_id) if guild_valid else None
    participation = bool((chat or 0) > 0 or (voice_seconds or 0) > 0) if (chat is not None or voice_seconds is not None) else None
    supporter = bool(facts.get("server_tag")) or bool(_safe_datetime(facts.get("premium_since"))) or SUPPORTER_ROLE_ID in role_ids
    event_win = _event_win(event_docs, user_id, is_main=is_main, main_guild_id=main_guild_id) if db_ok and is_main else None

    values = {
        "days": days, "chat": chat, "voice_hours": voice_hours,
        "owner": 1.0 if is_main and facts.get("owner_id") is not None and str(facts.get("owner_id")) == user_id else 0.0,
        "participation": 1.0 if participation else (0.0 if participation is False else None),
        "active_days": float(active_count) if active_count is not None else None,
        "guild_xp": guild_xp, "event_win": 1.0 if event_win else (0.0 if event_win is False else None),
        "supporter": 1.0 if supporter else 0.0,
    }
    achievements = []
    newly_unlocked = []
    for aid, name, description, target, kind in ACHIEVEMENTS:
        current = values[kind]
        available = current is not None
        unlocked_now = bool(available and current >= target)
        # Supporter is a live entitlement; a stale earned record must not retain it.
        unlocked = unlocked_now if aid == "apoiador_do_cafe" else unlocked_now or _earned(profile_doc, aid)
        progress = 1.0 if unlocked else (max(0.0, min(1.0, current / target)) if available else 0.0)
        if db_ok and unlocked_now and not _earned(profile_doc, aid):
            newly_unlocked.append(aid)
        achievements.append({"id": aid, "name": name, "description": description, "progress": progress,
                             "unlocked": unlocked, "current": current if current is not None else 0.0,
                             "target": target, "available": available})

    configured_featured = profile_doc.get("featured") if isinstance(profile_doc, dict) else None
    unlocked_ids = {a["id"] for a in achievements if a["unlocked"]}
    if isinstance(configured_featured, list):
        featured = list(dict.fromkeys(str(aid) for aid in configured_featured if str(aid) in unlocked_ids))[:3]
    else:
        featured = [a["id"] for a in achievements if a["unlocked"]][:3]
    theme = _text(profile_doc.get("theme") if isinstance(profile_doc, dict) else None, "cafe").lower()
    if theme not in {"cafe", "sakura", "midnight"}:
        theme = "cafe"
    bio = _text(profile_doc.get("bio") if isinstance(profile_doc, dict) else None)[:100]
    vip_label = next((label for role, label in reversed(VIP_ROLE_LABELS.items()) if role in role_ids), "Sem VIP") if is_main else "Sem VIP"
    guild_name = _text(guild_doc.get("name") if guild_valid and guild_xp is not None else None,
                       "Sem guilda" if db_ok else "Guilda indisponível")
    joined_label = joined.strftime("%d/%m/%Y") if joined else "Data indisponível"
    return {
        "display_name": _text(facts.get("display_name"), "Membro")[:64], "username": _text(facts.get("username"))[:64],
        "server_name": _text(facts.get("server_name"), "Servidor")[:64], "joined_label": joined_label,
        "vip_label": vip_label, "guild_name": guild_name[:64],
        "chat_points": int(chat) if chat is not None else None, "voice_seconds": voice_seconds,
        "eter": int(eter) if eter is not None else None, "essencia": int(essencia) if essencia is not None else None,
        "bio": bio, "theme": theme, "featured": featured, "achievements": achievements,
        "data_available": bool(data_available), "newly_unlocked": newly_unlocked,
    }
