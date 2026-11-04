"""Generate a local profile preview without Discord or database access."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cogs.engagement.profile_renderer import BADGE_SPECS, render_profile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "scripts/output/profile_preview.png")
    parser.add_argument("--theme", choices=("cafe", "sakura", "midnight"), default="cafe")
    args = parser.parse_args()
    achievements = []
    for index, (aid, (name, _, description)) in enumerate(BADGE_SPECS.items()):
        achievements.append({"id": aid, "name": name, "description": description,
                             "progress": 1.0 if index < 8 else .9,
                             "unlocked": index < 8, "available": True})
    profile = {"display_name": "PRATI", "username": "devprati", "server_name": "Animes Café",
               "joined_label": "02/09/2025", "vip_label": "VIP Monarch",
               "guild_name": "Garotos de Programa", "chat_points": 63880,
               "voice_seconds": 770.5 * 3600, "eter": 862, "essencia": 85524,
               "theme": args.theme, "achievements": achievements,
               "bio": "Código, café e boas conversas. Criando histórias no Animes Café.",
               "featured": ["criador_da_hatsu", "lenda_do_cafe", "cafeinado"],
               "footer": "Prévia de design · dados e conquistas ilustrativos"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(render_profile(profile))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
