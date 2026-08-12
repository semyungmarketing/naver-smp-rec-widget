#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMP_PATH = os.path.join(BASE_DIR, "smp.json")
REC_PATH = os.path.join(BASE_DIR, "rec.json")
SMP_OUT = os.path.join(BASE_DIR, "smp_widget.png")
REC_OUT = os.path.join(BASE_DIR, "rec_widget.png")

W, H = 170, 130

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        path = FONT_BOLD if bold else FONT_REGULAR
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def fmt_num(n):
    if n is None:
        return "-"
    try:
        n = float(n)
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.2f}"
    except Exception:
        return str(n)


def fmt_date(yyyymmdd):
    if not yyyymmdd or len(str(yyyymmdd)) != 8:
        return ""
    s = str(yyyymmdd)
    return f"{s[0:4]}.{s[4:6]}.{s[6:8]}"


def fmt_time_kst(iso):
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        return kst.strftime("%H:%M")
    except Exception:
        return "-"


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def draw_gradient_bg(draw, w, h, top, bottom):
    for y in range(h):
        t = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)], fill=lerp_color(top, bottom, t))


def draw_card(title, mode, price_text, unit, meta_text, updated_iso, out_path):
    img = Image.new("RGB", (W, H), (20, 33, 61))
    draw = ImageDraw.Draw(img)
    draw_gradient_bg(draw, W, H, (20, 33, 61), (27, 42, 74))

    pad = 10

    draw.text((pad, 10), title, font=font(12, bold=True), fill=(159, 208, 255))
    dot_color = (74, 222, 128) if mode == "auto" else (250, 204, 21)
    draw.ellipse((W - pad - 8, 12, W - pad, 20), fill=dot_color)

    badge_text = "자동" if mode == "auto" else "수동"
    f8 = font(8)
    bw = draw.textlength(badge_text, font=f8)
    badge_x = W - pad - 14 - bw
    draw.rounded_rectangle((badge_x, 30, badge_x + bw + 6, 42), radius=3, fill=(44, 58, 92))
    badge_color = (159, 208, 255) if mode == "auto" else (250, 204, 21)
    draw.text((badge_x + 3, 31), badge_text, font=f8, fill=badge_color)

    f24 = font(24, bold=True)
    draw.text((pad, 48), price_text, font=f24, fill=(255, 255, 255))
    pw = draw.textlength(price_text, font=f24)
    draw.text((pad + pw + 4, 60), unit, font=font(11), fill=(184, 196, 221))

    draw.text((pad, 86), meta_text, font=font(9), fill=(136, 148, 172))
    footer = f"갱신 {fmt_time_kst(updated_iso)}" if updated_iso else "갱신 -"
    draw.text((pad, H - 20), footer, font=font(7), fill=(107, 120, 150))

    img.save(out_path)


def render_smp(smp):
    price = fmt_num(smp.get("price"))
    unit = smp.get("unit") or "원/kWh"
    if smp.get("price") is not None:
        meta = (
            f"{fmt_date(smp.get('tradeDay'))} {smp.get('tradHour')}시 기준"
            if smp.get("tradHour") is not None
            else fmt_date(smp.get("tradeDay"))
        )
    else:
        meta = "아직 값이 없어요"
    draw_card("SMP (육지)", smp.get("mode") or "manual", price, unit, meta, smp.get("updatedAt"), SMP_OUT)


def render_rec(rec):
    price = fmt_num(rec.get("landAvgPrc"))
    unit = rec.get("unit") or "원"
    meta = f"{fmt_date(rec.get('bzDd'))} 거래일 기준" if rec.get("landAvgPrc") is not None else "아직 값이 없어요"
    draw_card("REC 현물 평균가", rec.get("mode") or "manual", price, unit, meta, rec.get("updatedAt"), REC_OUT)


def main():
    smp = load_json(SMP_PATH, {})
    rec = load_json(REC_PATH, {})
    render_smp(smp)
    render_rec(rec)
    print(f"생성 완료 -> {SMP_OUT}, {REC_OUT}")


if __name__ == "__main__":
    main()
