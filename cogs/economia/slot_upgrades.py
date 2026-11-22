"""Prices and atomic checkout for paid capacity upgrades."""
from datetime import datetime, timezone

from database import eco_logs_col, eco_users_col, guilds_col, run_transaction, vip_col
from utils import get_data_guild_id

GUILD_BASE_CAPACITY = 10
PRICES = {"guild": (2000, 500), "vip": (1000, 250)}


class SlotPurchaseError(ValueError):
    pass


def slot_price(kind, current):
    base, step = PRICES[kind]
    return base + step * current


def guild_capacity(document):
    return GUILD_BASE_CAPACITY + document.get("extra_member_slots", 0)


def vip_extras(document, role_id):
    upgrade = (document or {}).get("member_slot_upgrade") or {}
    return upgrade.get("count", 0) if upgrade.get("role_id") == str(role_id) else 0


def buy_slot(kind, guild_id, actor_id, target_id, expected_count, operation_id, *, role_id=None, max_personal=None):
    """Commit the debit, upgraded capacity and receipt together."""
    now = datetime.now(timezone.utc)
    data_guild_id = str(get_data_guild_id(guild_id))
    receipt_id = f"member_slot:{operation_id}"
    actor_ids = {"$in": [actor_id, str(actor_id)]}

    def checkout(session):
        receipt = eco_logs_col.find_one({"_id": receipt_id, "user_id": str(actor_id), "kind": kind,
                                         "target_id": str(role_id if kind == "vip" else target_id)}, session=session)
        if receipt:
            return receipt["price"], receipt["extra_slots"]

        if kind == "guild":
            from cogs.guilda.finance import check_scope, GuildFinanceError, _record

            collection = guilds_col
            query = {"_id": target_id, "leader_id": actor_ids, "members.user_id": actor_ids}
        else:
            collection = vip_col
            owner_scope = [{"user_id": actor_ids}]
            if target_id in {str(actor_id), f"{guild_id}:{actor_id}"}:
                owner_scope.append({"user_id": {"$exists": False}})
            query = {
                "_id": target_id, "role_id": {"$in": [role_id, str(role_id)]}, "status": "active",
                "entitlement_active": {"$ne": False},
                "$and": [
                    {"$or": owner_scope},
                    {"$or": [{"guild_id": {"$exists": False}}, {"guild_id": {"$in": [guild_id, str(guild_id)]}}]},
                ],
            }

        document = collection.find_one(query, session=session)
        if not document:
            raise SlotPurchaseError("A guilda ou o cargo já não está disponível para esta compra.")
        if kind == "guild":
            try:
                check_scope(document, guild_id)
            except GuildFinanceError as error:
                raise SlotPurchaseError(str(error)) from error
            count = document.get("extra_member_slots", 0)
            update = {"extra_member_slots": count + 1}
        else:
            if vip_col.find_one({"_id": {"$ne": target_id}, "role_id": {"$in": [role_id, str(role_id)]}},
                                {"_id": 1}, session=session):
                raise SlotPurchaseError("Este cargo tem mais de um vínculo VIP. Consulte a administração.")
            count = vip_extras(document, role_id)
            update = {"member_slot_upgrade": {"role_id": str(role_id), "count": count + 1}}
        if count != expected_count:
            raise SlotPurchaseError("O preço mudou. Abra o comando novamente para conferir o valor atual.")
        price = slot_price(kind, count)
        from_reserve = min(price, document.get("slot_essence_balance", 0)) if kind == "guild" else 0
        personal = price - from_reserve
        if max_personal is not None and personal > max_personal:
            raise SlotPurchaseError("O saldo da reserva diminuiu. Abra o comando novamente para conferir o novo valor.")
        if personal:
            charged = eco_users_col.update_one(
                {"_id": f"{data_guild_id}:{actor_id}", "essencia": {"$gte": personal}},
                {"$inc": {"essencia": -personal}, "$set": {"updated_at": now}}, session=session,
            )
            if not charged.matched_count:
                raise SlotPurchaseError(f"Saldo pessoal insuficiente. Sua carteira precisa cobrir {personal:,} Essências.".replace(",", "."))
        changes = {"$set": update}
        if from_reserve:
            changes["$inc"] = {"slot_essence_balance": -from_reserve}
        updated = collection.update_one(query, changes, session=session)
        if updated.modified_count != 1:
            raise SlotPurchaseError("Não consegui aplicar a vaga. Nenhum valor foi cobrado.")
        eco_logs_col.insert_one({"_id": receipt_id, "type": "member_slot_purchase", "kind": kind,
                                 "guild_id": data_guild_id, "user_id": str(actor_id),
                                 "target_id": str(role_id if kind == "vip" else target_id),
                                 "price": price, "currency": "essencia", "extra_slots": count + 1,
                                 "from_reserve": from_reserve, "from_personal": personal,
                                 "created_at": now}, session=session)
        if kind == "guild":
            _record(session, receipt_id, target_id, "slot_purchase", now, actor_id=str(actor_id),
                    amount=price, from_reserve=from_reserve, from_personal=personal)
        return price, count + 1

    return run_transaction(checkout)
