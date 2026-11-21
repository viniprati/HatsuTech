"""Remove confirmed departures without changing collective guild totals."""
from datetime import datetime, timezone

from config import MAIN_GUILD_ID
from database import guilds_col, run_transaction
from .finance import membership_signature, utc_date


def main_server_scope():
    return {"$or": [{"server_id": {"$exists": False}},
                    {"server_id": {"$in": [MAIN_GUILD_ID, str(MAIN_GUILD_ID)]}}]}


def read_memberships(user_id=None):
    query = main_server_scope()
    if user_id is not None:
        query["members.user_id"] = {"$in": [user_id, str(user_id)]}
    return list(guilds_col.find(query, {"leader_id": 1, "members.user_id": 1, "members.joined_at": 1}))


def remove_departed(snapshot, absent_ids, present_ids):
    """Apply a Discord membership check to the same set of registered members."""
    if not absent_ids:
        return 0

    def apply(session):
        query = {"_id": snapshot["_id"], **main_server_scope()}
        current = guilds_col.find_one(query, session=session)
        if not current or membership_signature(current.get("members", [])) != membership_signature(snapshot.get("members", [])):
            return 0
        leader_id = int(current.get("leader_id") or 0)
        remaining = [record for record in current["members"] if int(record["user_id"]) not in absent_ids]
        departed = set(absent_ids)
        update = {}
        if leader_id in departed:
            candidates = [record for record in remaining if int(record["user_id"]) in present_ids]
            if candidates:
                # Missing legacy dates come last, with a stable ID tie-break.
                successor = min(candidates, key=lambda record: (
                    utc_date(record.get("joined_at")) or datetime.max.replace(tzinfo=timezone.utc),
                    int(record["user_id"]),
                ))
                update["$set"] = {"leader_id": int(successor["user_id"])}
            elif remaining:
                # Retry the leader on a later sweep if no successor was verified.
                departed.remove(leader_id)
            else:
                update["$set"] = {"leader_id": None}
        stored_ids = [record["user_id"] for record in current["members"] if int(record["user_id"]) in departed]
        if not stored_ids:
            return 0
        update["$pull"] = {"members": {"user_id": {"$in": stored_ids}}}
        guilds_col.update_one(query, update, session=session)
        return len(set(map(int, stored_ids)))

    return run_transaction(apply)
