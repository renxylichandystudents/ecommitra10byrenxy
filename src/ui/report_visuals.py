"""Visual laporan: diagram fishbone (SVG) dan panel SWOT 4 kuadran (HTML).

Tata letak mengikuti contoh referensi: fishbone dengan 3 tulang di atas dan 3 di bawah menuju kepala ikan berisi masalah
utama; SWOT berupa 4 kuadran berwarna dengan judul berbentuk pita dan kotak judul di tengah. Isi butir berasal dari
`src.core.report_analysis` (angka aplikasi), bukan teks tetap.
"""

from __future__ import annotations

import html
import textwrap

BONE_STYLE = {
    "Produk": ("#1d4ed8", "📦"),
    "Harga & Promosi": ("#ea580c", "🏷️"),
    "Tempat / Saluran": ("#15803d", "🏬"),
    "Pemasaran & Pengguna": ("#1e3a8a", "📣"),
    "Proses": ("#6b21a8", "⚙️"),
    "Lingkungan / Eksternal": ("#047857", "🌐"),
}
LEVEL_STYLE = {"masalah": ("#dc2626", "#991b1b", 700), "waspada": ("#f59e0b", "#92400e", 600), "aman": ("#16a34a", "#334155", 500)}
TOP, BOTTOM = ("Produk", "Harga & Promosi", "Tempat / Saluran"), ("Pemasaran & Pengguna", "Proses", "Lingkungan / Eksternal")

W, H, SPINE_Y = 1120, 780, 390
GAP = 248
BONE_DX, BONE_DY = 130, 290


def _lines(text: str, width: int, limit: int) -> list[str]:
    parts = textwrap.wrap(str(text), width=width, break_long_words=True) or [""]
    if len(parts) > limit:
        parts = parts[:limit]
        parts[-1] = parts[-1][: max(width - 1, 1)].rstrip() + "…"
    return parts


def _bone(name: str, items: list[dict], sx: float, top: bool) -> str:
    color, icon = BONE_STYLE.get(name, ("#475569", "•"))
    end_y = SPINE_Y - BONE_DY if top else SPINE_Y + BONE_DY
    end_x = sx - BONE_DX
    out = [f"<line x1='{sx}' y1='{SPINE_Y}' x2='{end_x}' y2='{end_y}' stroke='{color}' stroke-width='5' stroke-linecap='round'/>"]
    pill_w, pill_h = 240, 42
    pill_y = end_y - pill_h - 6 if top else end_y + 6
    out.append(f"<rect x='{end_x - pill_w / 2}' y='{pill_y}' width='{pill_w}' height='{pill_h}' rx='20' fill='{color}'/>"
               f"<text x='{end_x}' y='{pill_y + 29}' text-anchor='middle' font-size='14.5' font-weight='800' fill='#fff'>"
               f"{icon} {html.escape(name.upper())}</text>")
    items = items or [{"text": "Belum ada data untuk tulang ini", "level": "aman"}]
    step = (BONE_DY - 40) / max(len(items), 1)
    step = min(step, 56)
    for k, item in enumerate(items):
        dist = 38 + k * step + step / 2
        y = SPINE_Y - BONE_DY + dist if top else SPINE_Y + BONE_DY - dist
        x = end_x + (abs(y - end_y) / BONE_DY) * BONE_DX
        dot, ink, weight = LEVEL_STYLE.get(item.get("level", "aman"), LEVEL_STYLE["aman"])
        rows = _lines(item.get("text", ""), 25, 3)
        out.append(f"<line x1='{x - 26}' y1='{y}' x2='{x}' y2='{y}' stroke='{color}' stroke-width='2'/>"
                   f"<circle cx='{x}' cy='{y}' r='7' fill='{dot}' stroke='#fff' stroke-width='2'/>")
        first = y - (len(rows) - 1) * 8.5 + 5
        for i, row in enumerate(rows):
            out.append(f"<text x='{x - 32}' y='{first + i * 17}' text-anchor='end' font-size='14.5' font-weight='{weight}' fill='{ink}'>"
                       f"{html.escape(row)}</text>")
    return "".join(out)


def fishbone_svg(problem: str, bones: dict[str, list[dict]]) -> str:
    """Diagram tulang ikan: 3 tulang atas (Produk, Harga & Promosi, Tempat/Saluran) dan 3 bawah (Pemasaran & Pengguna,
    Proses, Lingkungan/Eksternal) menuju kepala berisi masalah utama."""
    hx = W - 190  # pangkal kepala ikan
    parts = [f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' style='width:100%;height:auto;font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif'>",
             f"<rect x='0' y='0' width='{W}' height='{H}' rx='18' fill='#f8fafc'/>",
             f"<path d='M 30 {SPINE_Y - 120} Q 95 {SPINE_Y - 30} 150 {SPINE_Y} Q 95 {SPINE_Y + 30} 30 {SPINE_Y + 120} Q 70 {SPINE_Y} 30 {SPINE_Y - 120} Z' fill='#1e3a5f'/>",
             f"<line x1='140' y1='{SPINE_Y}' x2='{hx - 20}' y2='{SPINE_Y}' stroke='#1e3a5f' stroke-width='9' stroke-linecap='round'/>",
             f"<polygon points='{hx - 25},{SPINE_Y - 16} {hx + 10},{SPINE_Y} {hx - 25},{SPINE_Y + 16}' fill='#1e3a5f'/>",
             f"<path d='M {hx} {SPINE_Y - 130} Q {W - 10} {SPINE_Y - 110} {W - 8} {SPINE_Y} Q {W - 10} {SPINE_Y + 110} {hx} {SPINE_Y + 130} "
             f"Q {hx + 35} {SPINE_Y} {hx} {SPINE_Y - 130} Z' fill='#1e3a5f'/>",
             f"<circle cx='{hx + 105}' cy='{SPINE_Y - 72}' r='11' fill='#fff'/>"]
    head = _lines(problem.upper(), 12, 5)
    first = SPINE_Y - (len(head) - 1) * 13 + 14
    for i, row in enumerate(head):
        parts.append(f"<text x='{hx + 98}' y='{first + i * 24}' text-anchor='middle' font-size='18' font-weight='800' fill='#fff'>{html.escape(row)}</text>")
    for i, name in enumerate(TOP):
        parts.append(_bone(name, bones.get(name, []), 355 + i * GAP, True))
    for i, name in enumerate(BOTTOM):
        parts.append(_bone(name, bones.get(name, []), 355 + i * GAP, False))
    parts.append("</svg>")
    return "".join(parts)


def fishbone_legend() -> str:
    chips = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:.35rem;margin-right:1rem'><span style='width:11px;height:11px;border-radius:50%;"
        f"background:{LEVEL_STYLE[k][0]};display:inline-block'></span>{label}</span>"
        for k, label in (("masalah", "Masalah (menyumbang ke masalah utama)"), ("waspada", "Perlu diwaspadai"), ("aman", "Sudah baik / pembanding")))
    return f"<div style='font-size:var(--fs-sm);color:#475569;margin:.3rem 0 .6rem'>{chips}</div>"


SWOT_STYLE = {
    "Strength": ("STRENGTHS", "Kekuatan", "#15803d", "#e9f6ee", "📈"),
    "Weakness": ("WEAKNESSES", "Kelemahan", "#c2410c", "#fdeee8", "⚠️"),
    "Opportunity": ("OPPORTUNITIES", "Peluang", "#1d4ed8", "#e8f0fb", "🧭"),
    "Threat": ("THREATS", "Ancaman", "#334155", "#eef0f4", "🛡️"),
}


def swot_html(items: dict[str, list[str]], *, title: str = "Analisis SWOT: peningkatan kinerja toko Shopee", subtitle: str = "") -> str:
    """Panel SWOT 4 kuadran berwarna dengan kotak judul di tengah."""
    quads = []
    for index, key in enumerate(("Strength", "Weakness", "Opportunity", "Threat")):
        name, local, color, bg, icon = SWOT_STYLE[key]
        right = index % 2 == 1
        bottom = index >= 2
        badge = (f"<span style='width:54px;height:54px;border-radius:50%;background:#fff;border:4px solid {color};display:inline-flex;align-items:center;"
                 f"justify-content:center;font-size:26px;flex:none'>{icon}</span>")
        label = (f"<span style='background:{color};color:#fff;border-radius:999px;padding:.35rem 1.1rem;font-weight:900;letter-spacing:.04em;"
                 f"font-size:1.25rem'>{name}</span><span style='color:{color};font-weight:700;font-size:var(--fs-sm)'>{local}</span>")
        header = (f"<div style='display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;{'flex-direction:row-reverse;' if right else ''}'>"
                  f"{badge}{label}</div>")
        rows = "".join(f"<li style='margin:.28rem 0'>{html.escape(str(t))}</li>" for t in (items.get(key) or ["–"]))
        body = (f"<ol style='margin:.7rem 0 0 1.25rem;padding:0;font-weight:600;color:#0f172a;line-height:1.45;font-size:var(--fs-base)'>{rows}</ol>")
        pad = "1.1rem 1.4rem 1.2rem"
        if bottom:
            quads.append(f"<div style='background:{bg};padding:{pad};display:flex;flex-direction:column;"
                         f"{'border-left:2px solid #fff;' if right else ''}'>{body}<div style='margin-top:auto;padding-top:.6rem'>{header}</div></div>")
        else:
            quads.append(f"<div style='background:{bg};padding:{pad};{'border-left:2px solid #fff;' if right else ''}'>{header}{body}</div>")
    center = (f"<div style='grid-column:1 / span 2;display:flex;justify-content:center;padding:.55rem 0;"
              f"background:linear-gradient(90deg,#e9f6ee 50%,#fdeee8 50%)'><div style='background:#fff;border:3px solid #1e293b;border-radius:14px;"
              f"padding:.5rem 1.2rem;text-align:center;box-shadow:0 4px 14px rgba(15,23,42,.15);max-width:420px'>"
              f"<div style='font-weight:900;font-size:1.05rem;line-height:1.2;color:#0f172a;text-transform:uppercase'>{html.escape(title)}</div>"
              + (f"<div style='font-size:var(--fs-xs);color:#475569;margin-top:.2rem'>{html.escape(subtitle)}</div>" if subtitle else "") + "</div></div>")
    return ("<div style='position:relative;display:grid;grid-template-columns:1fr 1fr;border-radius:22px;overflow:hidden;border:1px solid #e2e8f0;"
            f"margin:.4rem 0 .8rem;break-inside:avoid'>{quads[0]}{quads[1]}{center}{quads[2]}{quads[3]}</div>")
