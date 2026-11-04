"""Rebuild the original SVG and transparent PNG badges from shared geometry."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets/profile/badges"
INK = "#ecf4ef"
BASE = "#163b46"
ACCENTS = ("#94cfb4", "#edbd83", "#8acbe0", "#b5ace2", "#a7c5eb",
           "#ace0c3", "#efa47c", "#87c8c2", "#e9cf85", "#e6a8b7")
IDS = ("lenda_do_cafe", "cafeinado", "voz_do_cafe", "criador_da_hatsu", "maratonista",
       "primeiro_gole", "presenca_marcante", "alma_da_guilda", "campeao_de_eventos", "apoiador_do_cafe")


def geometry(index):
    """64 px design grid; shapes stay inside an eight-pixel safe area."""
    accent = ACCENTS[index]
    shapes = [("ellipse", (3, 3, 61, 61), BASE, None, 0),
              ("ellipse", (5, 5, 59, 59), None, accent, 1.5)]

    def line(points, color=INK, width=2.5):
        shapes.append(("line", points, color, width))

    def rect(box, radius=3, color=INK):
        shapes.append(("rect", box, radius, None, color, 2.5))

    def arc(box, start, end, color=INK):
        shapes.append(("arc", box, start, end, color, 2.5))

    def cup():
        line([(18, 29), (18, 36), (21, 43), (25, 46), (37, 46), (41, 43), (43, 36), (43, 29), (18, 29)])
        arc((37, 30, 51, 41), 270, 450)
        line([(18, 49), (44, 49)], accent)

    if index == 0:
        rect((17, 20, 47, 46))
        line([(17, 28), (47, 28)], accent)
        line([(24, 16), (24, 23)])
        line([(40, 16), (40, 23)])
        line([(26, 37), (30, 41), (38, 33)], accent, 3)
    elif index == 1:
        cup()
        line([(28, 23), (26, 20), (28, 16)], accent)
        line([(35, 23), (33, 20), (35, 16)], accent)
    elif index == 2:
        rect((26, 15, 38, 37), 6)
        arc((20, 23, 44, 43), 0, 180, accent)
        line([(20, 27), (20, 33)], accent)
        line([(44, 27), (44, 33)], accent)
        line([(32, 43), (32, 49)])
        line([(25, 49), (39, 49)])
    elif index == 3:
        line([(24, 23), (15, 32), (24, 41)])
        line([(40, 23), (49, 32), (40, 41)])
        line([(36, 19), (28, 45)], accent)
    elif index == 4:
        arc((18, 17, 46, 45), 180, 360)
        line([(18, 31), (18, 43)])
        line([(46, 31), (46, 43)])
        rect((15, 31, 22, 43), 3, accent)
        rect((42, 31, 49, 43), 3, accent)
        line([(27, 49), (32, 44), (37, 49)], accent)
    elif index == 5:
        cup()
        line([(32, 29), (32, 20)], accent)
        line([(32, 23), (25, 22), (23, 17), (29, 17), (32, 23)], accent)
        line([(32, 23), (39, 22), (41, 17), (35, 17), (32, 23)], accent)
    elif index == 6:
        line([(32, 14), (31, 24), (23, 20), (17, 34), (19, 43), (26, 49),
              (38, 49), (45, 43), (47, 34), (42, 24), (39, 32), (32, 14)])
        arc((25, 34, 39, 47), 0, 360, accent)
        line([(35, 35), (29, 45)], accent)
    elif index == 7:
        line([(32, 14), (47, 21), (44, 39), (39, 47), (32, 51), (25, 47),
              (20, 39), (17, 21), (32, 14)])
        arc((25, 25, 39, 42), 0, 360, accent)
        line([(35, 26), (29, 40)], accent)
    elif index == 8:
        line([(32, 15), (37, 25), (48, 27), (40, 35), (42, 47), (32, 41),
              (22, 47), (24, 35), (16, 27), (27, 25), (32, 15)], accent)
        line([(32, 26), (32, 35)])
        line([(30, 35), (34, 35)])
    else:
        line([(32, 47), (18, 34), (16, 28), (18, 22), (24, 19), (29, 20),
              (32, 24), (35, 20), (40, 19), (46, 22), (48, 28), (46, 34), (32, 47)], accent)
        line([(25, 31), (25, 36), (28, 39), (34, 39), (37, 36), (37, 31), (25, 31)])
        arc((34, 31, 42, 37), 270, 450)
    return shapes


def build_badge(index):
    # A single geometry list drives both exported formats; Pillow is build/runtime's existing dependency.
    shapes = geometry(index)
    scale = 6
    image = Image.new("RGBA", (64 * scale, 64 * scale))
    draw = ImageDraw.Draw(image)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">']

    def box(value):
        return tuple(round(x * scale) for x in value)

    for item in shapes:
        kind = item[0]
        if kind in {"ellipse", "rect"}:
            bounds = item[1]
            radius, fill, stroke, width = (0, *item[2:]) if kind == "ellipse" else item[2:]
            if kind == "ellipse":
                draw.ellipse(box(bounds), fill=fill, outline=stroke, width=max(1, round(width * scale)))
                tag = f'<ellipse cx="{(bounds[0]+bounds[2])/2}" cy="{(bounds[1]+bounds[3])/2}" rx="{(bounds[2]-bounds[0])/2}" ry="{(bounds[3]-bounds[1])/2}"'
            else:
                draw.rounded_rectangle(box(bounds), radius=round(radius * scale), fill=fill, outline=stroke, width=round(width * scale))
                tag = f'<rect x="{bounds[0]}" y="{bounds[1]}" width="{bounds[2]-bounds[0]}" height="{bounds[3]-bounds[1]}" rx="{radius}"'
            svg.append(tag + f' fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{width}"/>')
            continue
        if kind == "line":
            points, color, width = item[1:]
        else:
            bounds, start, end, color, width = item[1:]
            cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
            rx, ry = (bounds[2] - bounds[0]) / 2, (bounds[3] - bounds[1]) / 2
            points = [(cx + rx * math.cos(math.radians(angle)), cy + ry * math.sin(math.radians(angle)))
                      for angle in range(start, end + 1, 3)]
        draw.line([(round(x * scale), round(y * scale)) for x, y in points], fill=color,
                  width=round(width * scale), joint="curve")
        for x, y in (points[0], points[-1]):
            r = width * scale / 2
            draw.ellipse((round(x*scale-r), round(y*scale-r), round(x*scale+r), round(y*scale+r)), fill=color)
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        svg.append(f'<polyline points="{coords}" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')
    svg.append("</svg>")
    return "\n".join(svg) + "\n", image.resize((256, 256), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(IDS):
        svg, image = build_badge(index)
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        image.save(OUT / f"{name}.png", optimize=True)
    print(f"Built {len(IDS)} SVG/PNG badge pairs in {OUT}")


if __name__ == "__main__":
    main()
