"""Portable Pillow renderer for the Animes Café member card; no network I/O."""
from __future__ import annotations

from functools import lru_cache
import io
import logging
import math
from pathlib import Path
import unicodedata
import warnings

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .profile_rules import ACHIEVEMENTS

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
# parents[0]=engagement, [1]=cogs, [2]=repository.
BADGE_DIR = ROOT / "assets/profile/badges"
FONT_DIR = ROOT / "assets/profile/fonts"
BADGE_SPECS = {aid: (name, kind, description) for aid, name, description, _, kind in ACHIEVEMENTS}
PALETTE = {
    "cafe": {"bg": "#102c36", "panel": "#173b45", "accent": "#94dcc7", "warm": "#efc58d", "line": "#31545d"},
    "sakura": {"bg": "#322b41", "panel": "#43374f", "accent": "#ecb4c8", "warm": "#e9cea1", "line": "#63546f"},
    "midnight": {"bg": "#182638", "panel": "#21364c", "accent": "#aacbf0", "warm": "#d7c7ee", "line": "#3e5671"},
}
TEXT = "#edf3ed"
MUTED = "#a6bdc0"
SIZE = (1400, 1000)
MAX_AVATAR_BYTES = 2_000_000
MAX_AVATAR_PIXELS = 4_000_000


@lru_cache(maxsize=96)
def _font(size: int, bold: bool = False):
    name = "Montserrat-SemiBold.otf" if bold else "Montserrat-Regular.otf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _safe(value, limit=100):
    return "".join(c for c in str(value or "") if unicodedata.category(c) not in {"Cc", "Cf", "Cs"})[:limit].strip()


def _fit(text, size, width, bold=False):
    text = _safe(text, 200)
    font = _font(size, bold)
    while size > 12 and font.getlength(text) > width:
        size -= 1
        font = _font(size, bold)
    while text and font.getlength(text) > width:
        text = text[:-1]
    return text, font


def _text(draw, xy, text, size, fill=TEXT, width=1000, bold=False, center=False):
    text, font = _fit(text, size, width, bold)
    x, y = xy
    if center:
        x -= font.getlength(text) / 2
    draw.text((round(x), y), text, fill=fill, font=font)


def _wrap(text, width, size=16, max_lines=3):
    font = _font(size)
    lines, line = [], ""
    for word in _safe(text, 100).split():
        candidate = f"{line} {word}".strip()
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line and font.getlength(candidate) > width:
            lines.append(line)
            line = ""
        for char in word:
            if font.getlength(line + char) > width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-2] + "…"
    return lines


def _number(value, suffix="", decimals=0):
    if value is None or isinstance(value, bool):
        return "Indisponível"
    try:
        value = float(value)
        if not math.isfinite(value) or value < 0:
            return "Indisponível"
        result = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return result + suffix
    except (ValueError, TypeError, OverflowError):
        return "Indisponível"


def _progress(value):
    try:
        value = float(value)
        return min(1, max(0, value)) if math.isfinite(value) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


@lru_cache(maxsize=30)
def _badge_image(aid, size, muted=False):
    with Image.open(BADGE_DIR / f"{aid}.png") as source:
        icon = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    if muted:
        alpha = icon.getchannel("A")
        icon = ImageOps.colorize(ImageOps.grayscale(icon), "#233e48", "#98afb1").convert("RGBA")
        icon.putalpha(alpha)
    return icon


def _avatar(data, accent):
    if data and len(data) <= MAX_AVATAR_BYTES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as source:
                    if source.width * source.height > MAX_AVATAR_PIXELS:
                        raise ValueError("avatar_dimensions")
                    return ImageOps.fit(source.convert("RGB"), (142, 142), method=Image.Resampling.LANCZOS)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            log.debug("profile_avatar_fallback source=image_validation")
    avatar = Image.new("RGB", (142, 142), "#284d57")
    draw = ImageDraw.Draw(avatar)
    draw.ellipse((50, 28, 92, 70), fill=accent)
    draw.rounded_rectangle((29, 80, 113, 147), 40, fill=accent)
    return avatar


def render_profile(profile: dict, avatar_bytes: bytes | None = None) -> bytes:
    """Draw the real card using packaged fonts and the same SVG/PNG badge set."""
    colors = PALETTE.get(profile.get("theme"), PALETTE["cafe"])
    bg, panel, accent, warm, line = (colors[k] for k in ("bg", "panel", "accent", "warm", "line"))
    image = Image.new("RGB", SIZE, bg)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 1376, 976), radius=28, outline=line, width=2)
    # A small café mark and an open header make this a member card.
    logo = _badge_image("primeiro_gole", 58)
    image.paste(logo, (53, 44), logo)
    _text(draw, (126, 50), profile.get("server_name") or "Animes Café", 29, width=900, bold=True)
    _text(draw, (126, 88), "Seu lugar no Café", 14, fill=MUTED)
    _text(draw, (1192, 66), "HatsuTech", 17, fill=accent, width=150)
    draw.line((62, 120, 1338, 120), fill=line, width=1)

    avatar = _avatar(avatar_bytes, accent)
    mask = Image.new("L", avatar.size)
    ImageDraw.Draw(mask).ellipse((0, 0, 141, 141), fill=255)
    image.paste(avatar, (64, 158), mask)
    draw.ellipse((61, 155, 208, 302), outline=accent, width=2)
    _text(draw, (236, 150), profile.get("display_name") or "Membro", 42, width=575, bold=True)
    _text(draw, (238, 205), "@" + _safe(profile.get("username"), 64).lstrip("@"), 17, fill=MUTED, width=570)
    _text(draw, (238, 247), "No Café desde " + _safe(profile.get("joined_label")), 15, width=575)
    team = _safe(profile.get("guild_name")) or "Sem guilda"
    _text(draw, (238, 276), team, 15, fill=accent, width=575)

    draw.line((846, 154, 846, 319), fill=line, width=1)
    _text(draw, (878, 154), profile.get("vip_label") or "Sem VIP", 15, fill=warm, width=435, bold=True)
    bio = profile.get("bio") or "Toda boa conversa começa com um café."
    for index, text in enumerate(_wrap(bio, 435, max_lines=2)):
        _text(draw, (878, 189 + 24*index), text, 16, width=435)
    achievements = {a["id"]: a for a in profile.get("achievements", []) if isinstance(a, dict) and a.get("id") in BADGE_SPECS}
    featured = [aid for aid in profile.get("featured", []) if aid in achievements and achievements[aid].get("unlocked")][:3]
    if featured:
        _text(draw, (878, 261), "Em destaque", 13, fill=MUTED, width=130)
        for index, aid in enumerate(featured):
            icon = _badge_image(aid, 48)
            image.paste(icon, (1015 + index*65, 247), icon)

    draw.rounded_rectangle((62, 346, 1338, 445), radius=16, fill=panel)
    voice = profile.get("voice_seconds")
    try:
        hours = float(voice) / 3600 if voice is not None else None
    except (ValueError, TypeError, OverflowError):
        hours = None
    stats = (("Pontos de chat", _number(profile.get("chat_points"))),
             ("Horas no ranking de voz", _number(hours, " h", 1)),
             ("Éter", _number(profile.get("eter"))), ("Essência", _number(profile.get("essencia"))))
    for index, (label, value) in enumerate(stats):
        x = 87 + index*319
        _text(draw, (x, 364), label, 14, fill=MUTED, width=270)
        _text(draw, (x, 389), value, 29, width=270, bold=True)
        if index < 3:
            draw.line((x+288, 365, x+288, 426), fill=line)

    _text(draw, (62, 476), "Conquistas do Café", 27, width=820, bold=True)
    unlocked_count = sum(bool(a.get("unlocked")) for a in achievements.values())
    _text(draw, (1110, 485), f"{unlocked_count} de 10", 18, fill=accent, width=220)
    for index, (aid, (name, _, _)) in enumerate(BADGE_SPECS.items()):
        a = achievements.get(aid, {})
        unlocked, available = bool(a.get("unlocked")), bool(a.get("available"))
        progress = 1 if unlocked else _progress(a.get("progress"))
        x, y = 62 + (index % 5)*260, 532 + (index // 5)*207
        draw.rounded_rectangle((x, y, x+236, y+181), radius=14, fill=panel)
        icon = _badge_image(aid, 88, not unlocked)
        image.paste(icon, (x+74, y+9), icon)
        _text(draw, (x+118, y+103), name, 16, width=218, bold=True, center=True)
        status = "Desbloqueada" if unlocked else (f"{int(progress*100)}% concluído" if available else "Sem dados ainda")
        _text(draw, (x+118, y+132), status, 13, fill=accent if unlocked else MUTED, width=218, center=True)
        draw.rounded_rectangle((x+20, y+162, x+216, y+166), radius=2, fill=line)
        if progress > 0:
            draw.rounded_rectangle((x+20, y+162, x+20+max(3, round(196*progress)), y+166), radius=2,
                                   fill=accent if unlocked else warm)
    footer = profile.get("footer") or "Faça parte. Converse. Deixe sua marca."
    _text(draw, (62, 947), footer, 12, fill=MUTED, width=1260)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
