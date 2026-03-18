#!/usr/bin/env python3
"""
PTR Card Generator — Federal Stock Report style.

Generates 1080x1080 Periodic Transaction Report card images using the
exact InDesign template specs (2550x2550 canvas, Graveur Variable font,
background PNG with baked-in static elements).
"""

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os
import re

# --- Asset paths ---
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
BG_PATH = os.path.join(ASSETS_DIR, "template_background.png")

# Graveur Variable font paths — bundled in assets, fallback to Adobe sync
_BUNDLED_REG = os.path.join(ASSETS_DIR, "Graveur-Regular.otf")
_BUNDLED_ITAL = os.path.join(ASSETS_DIR, "Graveur-Italic.otf")
_ADOBE_FONT_DIR = os.path.expanduser(
    "~/Library/Application Support/Adobe/CoreSync/plugins/livetype/.w"
)
_ADOBE_REG = os.path.join(_ADOBE_FONT_DIR, ".55420.otf")
_ADOBE_ITAL = os.path.join(_ADOBE_FONT_DIR, ".55421.otf")
GRAVEUR_REG = _BUNDLED_REG if os.path.exists(_BUNDLED_REG) else _ADOBE_REG
GRAVEUR_ITAL = _BUNDLED_ITAL if os.path.exists(_BUNDLED_ITAL) else _ADOBE_ITAL

# --- Colors (sampled from designer's rendered PDF) ---
BLACK = (0, 0, 0)
RED = (200, 61, 52)         # #c83d34
GREEN = (79, 138, 79)       # #4f8a4f
DETAIL_GRAY = (150, 150, 150)
ROW_SEP = (102, 102, 102)

# --- Canvas size ---
CANVAS = 2550
OUTPUT = 1080
S = 2550 / 612  # pt-to-px scale

# --- Layout (IDML positions) ---
MARGIN = 150
CONTENT_RIGHT = 2400

# Em dash for missing data
EM_DASH = "\u2014"

AMOUNT_ORDER = {
    "$1,001 - $15,000": 1,
    "$15,001 - $50,000": 2,
    "$50,001 - $100,000": 3,
    "$100,001 - $250,000": 4,
    "$250,001 - $500,000": 5,
    "$500,001 - $1,000,000": 6,
    "$1,000,001 - $5,000,000": 7,
    "$5,000,001 - $25,000,000": 8,
    "$25,000,001 - $50,000,000": 9,
}

AMOUNT_RANGES = {
    "$1,001 - $15,000": (1001, 15000),
    "$15,001 - $50,000": (15001, 50000),
    "$50,001 - $100,000": (50001, 100000),
    "$100,001 - $250,000": (100001, 250000),
    "$250,001 - $500,000": (250001, 500000),
    "$500,001 - $1,000,000": (500001, 1000000),
    "$1,000,001 - $5,000,000": (1000001, 5000000),
    "$5,000,001 - $25,000,000": (5000001, 25000000),
    "$25,000,001 - $50,000,000": (25000001, 50000000),
}

# Table column positions (x coords in 2550 canvas)
COL_ASSET_X = 180
COL_OWNER_X = 1127
COL_OWNER_W = 136
COL_TYPE_X = 1319
COL_TYPE_W = 136
COL_TXDATE_X = 1440
COL_TXDATE_W = 250
COL_NOTIF_X = 1690
COL_NOTIF_W = 250
COL_AMOUNT_X = 1960
COL_AMOUNT_W = 440

# Table row Y positions (text frame tops for 6 rows)
ROW_Y_POSITIONS = [1250, 1416, 1582, 1749, 1916, 2082]
ROW_HEIGHT = 89

# Row separator Y positions
ROW_SEP_Y = [1377, 1543, 1709, 1877, 2043, 2209]


def _graveur(size, instance_name, italic=False):
    path = GRAVEUR_ITAL if italic else GRAVEUR_REG
    font = ImageFont.truetype(path, size)
    font.set_variation_by_name(instance_name.encode())
    return font


def get_fonts():
    fonts = {}
    fonts["title"] = _graveur(int(30 * S), "Display Heavy")
    fonts["label"] = _graveur(int(12 * S), "Heavy")
    fonts["value"] = _graveur(int(16 * S), "Subhead")
    fonts["stats"] = _graveur(int(18 * S), "Subhead Heavy")
    fonts["stats_sep"] = _graveur(int(18 * S), "Subhead")
    fonts["td_asset"] = _graveur(int(11 * S), "Heavy")
    fonts["td_asset_code"] = _graveur(int(9 * S), "Regular")  # smaller, non-bold for [ST] etc.
    fonts["td"] = _graveur(int(11 * S), "Regular")
    fonts["td_type"] = _graveur(int(11 * S), "Heavy")
    fonts["td_amount"] = _graveur(int(11 * S), "Heavy")
    fonts["detail"] = _graveur(int(9 * S), "Book Italic", italic=True)
    fonts["overflow"] = _graveur(int(8 * S), "Heavy")
    fonts["footnote"] = _graveur(int(8 * S), "Regular")
    return fonts


def calc_totals(txns):
    lo = sum(AMOUNT_RANGES.get(t["amount"], (0, 0))[0] for t in txns)
    hi = sum(AMOUNT_RANGES.get(t["amount"], (0, 0))[1] for t in txns)
    return lo, hi


def fmt(n):
    return f"${n:,.0f}"


def format_district(d):
    letters = "".join(c for c in d if c.isalpha())
    digits = "".join(c for c in d if not c.isalpha())
    if not digits:
        return letters  # Senate: just state code, no district number
    return f"{letters}-{digits}"


def _split_asset_and_code(asset_str):
    """Split 'Apple Inc. (AAPL) [ST]' into ('Apple Inc. (AAPL)', '[ST]')."""
    match = re.search(r'\s*(\[[A-Z]{2,4}\])\s*$', asset_str)
    if match:
        code = match.group(1)
        name = asset_str[:match.start()].strip()
        return name, code
    return asset_str, ""


def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit within max_width. Returns list of lines."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def _cx(draw, text, font, col_x, col_w, y, fill=BLACK):
    """Draw text horizontally centered in a column."""
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    draw.text((col_x + (col_w - tw) // 2, y), text, fill=fill, font=font)


def _bly(font, ref, y):
    """Baseline-align font with ref font at y."""
    return y + (ref.getmetrics()[0] - font.getmetrics()[0])


def _draw_title_with_fixed_zero(img, draw, font, text, x, y):
    """Render title text, rotating any '0' characters 90° to fix old-style figures."""
    cursor_x = x
    for ch in text:
        if ch == '0':
            bbox = font.getbbox('0')
            ch_w = bbox[2] - bbox[0]
            ch_h = bbox[3] - bbox[1]
            pad = 20
            tmp = Image.new("RGBA", (ch_w + pad * 2, ch_h + pad * 2), (0, 0, 0, 0))
            tmp_draw = ImageDraw.Draw(tmp)
            tmp_draw.text((pad - bbox[0], pad - bbox[1]), '0', fill=BLACK, font=font)
            rotated = tmp.rotate(-90, resample=Image.BICUBIC, expand=True)
            rw, rh = rotated.size
            paste_x = int(cursor_x + (ch_w - rw) // 2)
            paste_y = int(y + bbox[1] + (ch_h - rh) // 2)
            img.paste(rotated, (paste_x, paste_y), rotated)
            cursor_x += ch_w
        else:
            draw.text((cursor_x, y), ch, fill=BLACK, font=font)
            cursor_x += draw.textlength(ch, font=font)


def _recolor_logo(img, target_red):
    """Replace the bright red pixels in the logo with target red."""
    data = np.array(img)
    r, g, b, a = data[:, :, 0], data[:, :, 1], data[:, :, 2], data[:, :, 3]
    mask = (r > 150) & (g < 100) & (b < 100) & (a > 128)
    data[mask, 0] = target_red[0]
    data[mask, 1] = target_red[1]
    data[mask, 2] = target_red[2]
    return Image.fromarray(data)


def generate_ptr_card(data, output_path):
    fonts = get_fonts()
    transactions = data["transactions"]
    num_tx = len(transactions)
    total_lo, total_hi = calc_totals(transactions)

    # Load background template and recolor logo to match our RED
    bg = Image.open(BG_PATH).convert("RGBA")
    bg = _recolor_logo(bg, RED)

    # White out the baked-in header labels from TYPE onward so we can redraw
    bg_data = np.array(bg)
    bg_data[1145:1220, 1290:2400, :] = 0  # clear from TYPE column onward
    bg = Image.fromarray(bg_data)

    # Create white base and composite background on top
    img = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)

    # Redraw the cleared header area with dark bar and labels
    th_font = _graveur(int(8 * S), "Heavy")
    draw.rectangle([1290, 1145, 2400, 1220], fill=(36, 31, 33))
    th_y = 1145 + 25
    _cx(draw, "TYPE", th_font, COL_TYPE_X, COL_TYPE_W, th_y, fill=(255, 255, 255))
    _cx(draw, "TX DATE", th_font, COL_TXDATE_X, COL_TXDATE_W, th_y, fill=(255, 255, 255))
    _cx(draw, "NOTIF DATE", th_font, COL_NOTIF_X, COL_NOTIF_W, th_y, fill=(255, 255, 255))
    _cx(draw, "AMOUNT", th_font, COL_AMOUNT_X, COL_AMOUNT_W, th_y, fill=(255, 255, 255))

    # ── 1. Member Name (hero title) ──
    dist = format_district(data["district"])
    title_text = f"{data['name']} ({dist})" if dist else data["name"]

    # Auto-shrink title font if text is too wide for the canvas
    max_title_w = CONTENT_RIGHT - MARGIN
    title_font = fonts["title"]
    title_size = int(30 * S)
    # Measure width with the default font
    test_w = draw.textlength(title_text, font=title_font)
    while test_w > max_title_w and title_size > int(16 * S):
        title_size -= int(1 * S)
        title_font = _graveur(title_size, "Display Heavy")
        test_w = draw.textlength(title_text, font=title_font)

    _draw_title_with_fixed_zero(img, draw, title_font, title_text, MARGIN, 375)

    # ── 2. Filing Info ──
    y_info = 690
    lf, vf = fonts["label"], fonts["value"]

    # Strip chamber prefix (REP./SEN.) for the NAME field
    display_name = re.sub(r'^(?:REP|SEN)\.?\s*', '', data["name"], flags=re.IGNORECASE).title()
    for lbl, val in [("FILING ID: ", f"#{data['filing_id']}"),
                     ("NAME: ", display_name)]:
        draw.text((MARGIN, y_info), lbl, fill=BLACK, font=lf)
        lx = MARGIN + draw.textlength(lbl, font=lf)
        draw.text((lx, _bly(vf, lf, y_info)), val, fill=BLACK, font=vf)
        y_info += 75

    # Status / State-District / Party on one line
    draw.text((MARGIN, y_info), "STATUS: ", fill=BLACK, font=lf)
    sx = MARGIN + draw.textlength("STATUS: ", font=lf)
    vy = _bly(vf, lf, y_info)
    draw.text((sx, vy), data["status"], fill=BLACK, font=vf)

    # Use "STATE:" for senators, "STATE/DISTRICT:" for reps
    is_senator = data.get("status", "").lower() == "senator"
    state_label = "STATE: " if is_senator else "STATE/DISTRICT: "
    draw.text((852, y_info), state_label, fill=BLACK, font=lf)
    dx = 852 + draw.textlength(state_label, font=lf)
    draw.text((dx, vy), dist, fill=BLACK, font=vf)

    draw.text((1569, y_info), "PARTY: ", fill=BLACK, font=lf)
    px = 1569 + draw.textlength("PARTY: ", font=lf)
    draw.text((px, vy), data["party"], fill=BLACK, font=vf)

    # ── 3. Stats Bar ──
    stats_y = 964
    x = MARGIN
    ct = f"{num_tx} Transaction{'s' if num_tx != 1 else ''}"
    sep = " | "
    at = f"Total: {fmt(total_hi)} - {fmt(total_lo)}"

    draw.text((x, stats_y), ct, fill=RED, font=fonts["stats"])
    x += draw.textlength(ct, font=fonts["stats"])
    draw.text((x, stats_y), sep, fill=BLACK, font=fonts["stats_sep"])
    x += draw.textlength(sep, font=fonts["stats_sep"])
    draw.text((x, stats_y), at, fill=RED, font=fonts["stats"])

    # ── 4. Table Data Rows ──
    # Sort: pinned first, then by amount descending
    pinned_keys = data.get("pinned", [])
    pinned, rest = [], []
    if pinned_keys:
        used = set()
        for k in pinned_keys:
            kl = k.lower()
            for i, t in enumerate(transactions):
                if i not in used and kl in t["asset"].lower():
                    pinned.append(t)
                    used.add(i)
                    break
        rest = [t for i, t in enumerate(transactions) if i not in used]
    else:
        rest = list(transactions)
    rest.sort(key=lambda t: AMOUNT_ORDER.get(t["amount"], 0), reverse=True)
    sorted_tx = pinned + rest

    max_rows = len(ROW_Y_POSITIONS)
    display = sorted_tx[:max_rows]
    overflow = num_tx - len(display)

    # Track if any displayed transactions are partial (for footnote)
    has_partial = False

    for i, tx in enumerate(display):
        row_y = ROW_Y_POSITIONS[i]
        text_y = row_y + 25

        # Asset name — split into name + type code, wrap if too long
        asset_full = tx.get("asset", "")
        asset_name, asset_code = _split_asset_and_code(asset_full)

        # Max width for asset column (leave padding before OWNER)
        asset_max_w = COL_OWNER_X - COL_ASSET_X - 20

        # Combine name + code to check total width
        full_display = f"{asset_name} {asset_code}" if asset_code else asset_name
        full_w = draw.textlength(asset_name, font=fonts["td_asset"])
        if asset_code:
            full_w += draw.textlength(" " + asset_code, font=fonts["td_asset_code"])

        has_detail = bool(tx.get("detail"))

        if full_w <= asset_max_w:
            # Fits on one line
            ay = row_y + 12 if has_detail else text_y
            draw.text((COL_ASSET_X, ay), asset_name,
                       fill=BLACK, font=fonts["td_asset"])
            if asset_code:
                name_w = draw.textlength(asset_name + " ", font=fonts["td_asset"])
                code_y = _bly(fonts["td_asset_code"], fonts["td_asset"], ay)
                draw.text((COL_ASSET_X + name_w, code_y), asset_code,
                           fill=DETAIL_GRAY, font=fonts["td_asset_code"])
        else:
            # Wrap: use the full string (name + code) and wrap it
            # The code will naturally end up on the last line
            wrap_text = f"{asset_name} {asset_code}" if asset_code else asset_name
            wrapped = _wrap_text(wrap_text, fonts["td_asset"], asset_max_w, draw)
            line_h = 38  # line height in canvas px
            # Vertically center the wrapped lines in the row
            total_text_h = len(wrapped) * line_h
            start_y = row_y + (ROW_HEIGHT - total_text_h) // 2 + 5
            if has_detail:
                start_y = row_y + 8
            for li, wline in enumerate(wrapped):
                ly = start_y + li * line_h
                # Check if this line ends with the asset code
                if asset_code and wline.endswith(asset_code):
                    name_part = wline[:-len(asset_code)].rstrip()
                    draw.text((COL_ASSET_X, ly), name_part,
                               fill=BLACK, font=fonts["td_asset"])
                    nw = draw.textlength(name_part + " ", font=fonts["td_asset"])
                    code_y = _bly(fonts["td_asset_code"], fonts["td_asset"], ly)
                    draw.text((COL_ASSET_X + nw, code_y), asset_code,
                               fill=DETAIL_GRAY, font=fonts["td_asset_code"])
                else:
                    draw.text((COL_ASSET_X, ly), wline,
                               fill=BLACK, font=fonts["td_asset"])

        if has_detail:
            draw.text((COL_ASSET_X, row_y + 58), tx["detail"].upper(),
                       fill=DETAIL_GRAY, font=fonts["detail"])

        # Owner — em dash if missing
        owner = tx.get("owner", "").strip()
        _cx(draw, owner if owner else EM_DASH, fonts["td"],
            COL_OWNER_X, COL_OWNER_W, text_y)

        # Type — color-coded, with * for partial, em dash if missing
        tx_type = tx.get("type", "").strip()
        is_partial = tx.get("partial", False)
        if not tx_type:
            _cx(draw, EM_DASH, fonts["td"], COL_TYPE_X, COL_TYPE_W, text_y)
        else:
            tc = GREEN if tx_type == "P" else RED
            type_display = tx_type + "*" if is_partial else tx_type
            _cx(draw, type_display, fonts["td_type"],
                COL_TYPE_X, COL_TYPE_W, text_y, fill=tc)
            if is_partial:
                has_partial = True

        # Dates — em dash if missing
        tx_date = tx.get("tx_date", "").strip()
        notif_date = tx.get("notif_date", "").strip()
        _cx(draw, tx_date if tx_date else EM_DASH, fonts["td"],
            COL_TXDATE_X, COL_TXDATE_W, text_y)
        _cx(draw, notif_date if notif_date else EM_DASH, fonts["td"],
            COL_NOTIF_X, COL_NOTIF_W, text_y)

        # Amount — em dash if missing
        amount = tx.get("amount", "").strip()
        _cx(draw, amount if amount else EM_DASH, fonts["td"],
            COL_AMOUNT_X, COL_AMOUNT_W, text_y)

    # White out unused row slots (background has baked-in gray bands)
    if len(display) < len(ROW_Y_POSITIONS):
        last_used_sep = ROW_SEP_Y[len(display) - 1] if display else ROW_Y_POSITIONS[0]
        clear_top = last_used_sep + 1
        clear_bottom = ROW_SEP_Y[-1] + 50
        draw.rectangle([0, clear_top, CANVAS, clear_bottom], fill=(255, 255, 255, 255))

    # ── 5. Row separator lines ──
    for sy in ROW_SEP_Y[:len(display)]:
        draw.line([MARGIN, sy, CONTENT_RIGHT, sy], fill=ROW_SEP, width=1)

    # ── 6. Footnotes + Overflow ──
    # Position footnotes below the last row separator
    if display:
        footnote_y = ROW_SEP_Y[len(display) - 1] + 20
    else:
        footnote_y = 2220

    if has_partial:
        draw.text((MARGIN, footnote_y), "*Partial",
                  fill=BLACK, font=fonts["footnote"])
        footnote_y += 35

    if overflow > 0:
        overflow_url = data.get("source_url", "")
        if not overflow_url:
            overflow_url = (f"https://disclosures-clerk.house.gov/public_disc/"
                           f"ptr-pdfs/2026/{data['filing_id']}.pdf")
        draw.text((MARGIN, footnote_y),
                  f"Plus {overflow} additional transactions. See {overflow_url} for more.",
                  fill=BLACK, font=fonts["overflow"])

    # ── Downscale to 1080x1080 and save ──
    img = img.convert("RGB")
    img = img.resize((OUTPUT, OUTPUT), Image.LANCZOS)
    img.save(output_path, "PNG")
    print(f"Saved: {output_path} ({OUTPUT}x{OUTPUT})")
