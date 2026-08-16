from __future__ import annotations
from ..cog import *
from ..cog import _to_int_or_none


def _role_is_between(guild: discord.Guild, role: discord.Role, first_anchor_id: int, second_anchor_id: int) -> bool:
    first_anchor = guild.get_role(first_anchor_id)
    second_anchor = guild.get_role(second_anchor_id)
    if not first_anchor or not second_anchor:
        return False
    lower_anchor, upper_anchor = sorted((first_anchor, second_anchor), key=lambda anchor: anchor.position)
    return lower_anchor.position < role.position < upper_anchor.position


def _roles_between(guild: discord.Guild, first_anchor_id: int, second_anchor_id: int) -> list[discord.Role]:
    first_anchor = guild.get_role(first_anchor_id)
    second_anchor = guild.get_role(second_anchor_id)
    if not first_anchor or not second_anchor:
        return []
    lower_anchor, upper_anchor = sorted((first_anchor, second_anchor), key=lambda anchor: anchor.position)
    return [
        role
        for role in guild.roles
        if lower_anchor.position < role.position < upper_anchor.position
        and role.id not in {first_anchor_id, second_anchor_id}
        and not role.managed
    ]


def _role_label(role: discord.Role) -> str:
    return f"{role.name} (`{role.id}`)"


async def execute(self, it: discord.Interaction, incluir_nao_vinculados: bool = True):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "o comando /organizar_vips"):
        return

    guild = it.guild
    guild_id = str(guild.id)
    role_ids = [value for role in guild.roles for value in (str(role.id), role.id)]

    docs = await asyncio.to_thread(
        lambda: list(
            vip_col.find(
                {
                    "$or": [
                        {"guild_id": guild_id},
                        {
                            "guild_id": {"$exists": False},
                            "$or": [
                                {"role_id": {"$in": role_ids}},
                                {"highlight_id": {"$in": role_ids}},
                            ],
                        },
                    ]
                },
                {"role_id": 1, "highlight_id": 1, "guild_id": 1, "user_id": 1},
            )
        )
    )

    common_ids = set()
    highlight_ids = set()
    for doc in docs:
        if not self._vip_doc_belongs_to_guild(guild, doc):
            continue
        common_id = _to_int_or_none(doc.get("role_id"))
        highlight_id = _to_int_or_none(doc.get("highlight_id"))
        if common_id is not None:
            common_ids.add(common_id)
        if highlight_id is not None:
            highlight_ids.add(highlight_id)

    candidate_roles = {}
    for role_id in common_ids | highlight_ids:
        role = guild.get_role(role_id)
        if role and not role.managed and role.id not in VIP_CONFIG:
            candidate_roles[role.id] = role

    if incluir_nao_vinculados:
        for role in _roles_between(guild, VIP_COMMON_TOP_ROLE_ID, VIP_COMMON_BOTTOM_ROLE_ID):
            if role.id not in VIP_CONFIG:
                candidate_roles.setdefault(role.id, role)
        for role in _roles_between(guild, MONARCH_HIGHLIGHT_TOP_ROLE_ID, MONARCH_HIGHLIGHT_BOTTOM_ROLE_ID):
            if role.id not in VIP_CONFIG:
                candidate_roles.setdefault(role.id, role)

    moved_common = []
    moved_highlight = []
    already_ok = 0
    skipped = []
    failed = []

    for role in sorted(candidate_roles.values(), key=lambda r: r.position):
        if len(role.members) == 1:
            target = "highlight"
        elif len(role.members) > 1:
            target = "common"
        elif role.id in highlight_ids:
            target = "highlight"
        elif role.id in common_ids:
            target = "common"
        else:
            skipped.append(f"{_role_label(role)} sem membros")
            continue

        if target == "highlight":
            already_target = _role_is_between(
                guild,
                role,
                MONARCH_HIGHLIGHT_TOP_ROLE_ID,
                MONARCH_HIGHLIGHT_BOTTOM_ROLE_ID,
            )
            positioned = await self._position_monarch_highlight_role(guild, role)
            if positioned and already_target:
                already_ok += 1
            elif positioned:
                moved_highlight.append(_role_label(role))
            else:
                failed.append(f"{_role_label(role)} -> destaque")
            continue

        already_target = _role_is_between(guild, role, VIP_COMMON_TOP_ROLE_ID, VIP_COMMON_BOTTOM_ROLE_ID)
        positioned = await self._position_common_vip_role(guild, role)
        if positioned and already_target:
            already_ok += 1
        elif positioned:
            moved_common.append(_role_label(role))
        else:
            failed.append(f"{_role_label(role)} -> comum")

    def _section(title: str, values: list[str]) -> str:
        if not values:
            return f"**{title}:** 0"
        shown = "\n".join(f"- {value}" for value in values[:10])
        suffix = f"\n- ... +{len(values) - 10}" if len(values) > 10 else ""
        return f"**{title}:** {len(values)}\n{shown}{suffix}"

    message = "\n\n".join(
        [
            _section("Movidos para VIP comum", moved_common),
            _section("Movidos para destaque/exclusivo", moved_highlight),
            f"**Ja estavam corretos:** {already_ok}",
            _section("Ignorados", skipped),
            _section("Falhas", failed),
        ]
    )
    await it.followup.send(message[:1900], ephemeral=True)
