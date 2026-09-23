"""
make_demos.py -- three cover-slide options, so you can pick one by eye.

    python3 cover_demos/make_demos.py      (run from pipeline_scripts/)

Nothing in the real pipeline changes. This borrows the helpers from
poster_template.py (photos, fonts, camera chrome, bubble) and only redraws
the category + headline three different ways.

SAFE ZONE: the posts are 1080 x 1080, but Instagram's profile grid now shows
every post cropped to 3:4 (810 wide), so 135px vanish off each side. Every
option below keeps ALL text inside the middle 740px.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # so we can import poster_template
import poster_template as pt
from PIL import Image, ImageDraw, ImageFilter

W = H = 1080
SAFE_W = 740                       # widest any text may be
CATS = ["Technology, Data & AI", "Business, Commerce, Marketing & Finance", "Engineering"]
COUNTS = {CATS[0]: (6, 0), CATS[1]: (6, 0), CATS[2]: (6, 3)}


def base(cat):
    """Photo + scrims, same as the real cover."""
    ink, deep = pt.palette_for(cat)
    img = pt._background("cover" + cat[:4], deep, dim=0.10, blur=0).convert("RGBA")
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for r in range(H):                       # darken the middle band a bit more for readability
        mid = 1 - abs(r - H * 0.45) / (H * 0.45)
        sd.line([(0, r), (W, r)], fill=(0, 0, 0, int(95 * max(mid, 0))))
    for r in range(360):
        sd.line([(0, H - 1 - r), (W, H - 1 - r)], fill=(0, 0, 0, int(165 * (1 - r / 360))))
    img.alpha_composite(scrim)
    return img, ink


def fit(draw, text, weight, max_w, sizes):
    """Biggest font size from `sizes` whose text fits in max_w (like a loop in C)."""
    for s in sizes:
        f = pt._font(weight, s)
        if draw.textlength(text, font=f) <= max_w:
            return f
    return f


def shadow_text(img, xy, text, font, fill):
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((xy[0], xy[1] + 6), text, font=font, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill)


def finish(img, cat, y_bubble):
    d = ImageDraw.Draw(img)
    n, g = COUNTS[cat]
    msg = f"{n - g} internships + {g} grad roles" if g else f"{n} open right now"
    pt._bubble(d, W / 2, y_bubble, msg, pt._font("DejaVuSans-Bold.ttf", 40))
    pt._camera_chrome(img, d)
    h = "@berry.internships.syd"
    f = pt._font("DejaVuSans-Bold.ttf", 28)
    d.text(((W - d.textlength(h, font=f)) / 2, 62), h, font=f, fill=(255, 255, 255))
    return img


# ---- Option A: big SOLID pill in the category colour ------------------------
def option_a(cat):
    img, ink = base(cat)
    d = ImageDraw.Draw(img)
    label = pt.SHORT_CATEGORY[cat].upper()
    f = fit(d, label, "DejaVuSans-Bold.ttf", SAFE_W - 80, (64, 58, 52, 46))
    tw = d.textlength(label, font=f)
    pw, ph = tw + 80, f.size + 46
    x, y = (W - pw) / 2, 250
    d.rounded_rectangle([x, y, x + pw, y + ph], radius=ph / 2, fill=ink)
    d.text((x + 40, y + (ph - f.size * 1.36) / 2), label, font=f, fill=(255, 255, 255))
    fh = pt._font("DejaVuSans-Bold.ttf", 104)
    yy = y + ph + 40
    for line in ("Internships", "in Sydney"):
        lw = d.textlength(line, font=fh)
        shadow_text(img, ((W - lw) / 2, yy), line, fh, (255, 255, 255))
        yy += 118
    return finish(img, cat, yy + 40)


# ---- Option B: the CATEGORY is the headline ----------------------------------
def option_b(cat):
    img, ink = base(cat)
    d = ImageDraw.Draw(img)
    words = pt.SHORT_CATEGORY[cat].upper().replace(" & ", " &\n").split("\n")
    fb = pt._font("DejaVuSans-Bold.ttf", 10)
    for s in (150, 136, 124, 112, 100):
        fb = pt._font("DejaVuSans-Bold.ttf", s)
        if max(d.textlength(w, font=fb) for w in words) <= SAFE_W:
            break
    y = 230 if len(words) > 1 else 300
    for w in words:
        lw = d.textlength(w, font=fb)
        shadow_text(img, ((W - lw) / 2, y), w, fb, (255, 255, 255))
        y += int(fb.size * 1.08)
    # coloured bar, then the small line underneath
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W / 2 - 70, y + 16, W / 2 + 70, y + 30], radius=7, fill=ink)
    fs = pt._font("DejaVuSans-Bold.ttf", 50)
    sub = "internships in Sydney"
    shadow_text(img, ((W - d.textlength(sub, font=fs)) / 2, y + 52), sub, fs, (255, 255, 255))
    return finish(img, cat, y + 150)


# ---- Option C: colour BANNER across the safe zone ---------------------------
def option_c(cat):
    img, ink = base(cat)
    d = ImageDraw.Draw(img)
    label = pt.SHORT_CATEGORY[cat].upper()
    f = fit(d, label, "DejaVuSans-Bold.ttf", SAFE_W - 60, (78, 70, 62, 56, 50))
    bx0, bx1, by, bh = (W - SAFE_W) / 2, (W + SAFE_W) / 2, 240, f.size + 56
    d.rectangle([bx0, by, bx1, by + bh], fill=ink)
    tw = d.textlength(label, font=f)
    d.text(((W - tw) / 2, by + (bh - f.size * 1.36) / 2), label, font=f, fill=(255, 255, 255))
    fh = pt._font("DejaVuSans-Bold.ttf", 96)
    yy = by + bh + 44
    for line in ("Internships", "in Sydney"):
        lw = d.textlength(line, font=fh)
        shadow_text(img, ((W - lw) / 2, yy), line, fh, (255, 255, 255))
        yy += 110
    return finish(img, cat, yy + 40)


def grid_preview(tiles, path):
    """What the profile grid shows: each post cropped to 3:4 and shrunk."""
    tw, th = 270, 360
    sheet = Image.new("RGB", (tw * len(tiles) + 6 * (len(tiles) - 1), th), (12, 12, 14))
    for i, t in enumerate(tiles):
        crop = t.convert("RGB").crop((135, 0, 945, 1080)).resize((tw, th), Image.LANCZOS)
        sheet.paste(crop, (i * (tw + 6), 0))
    sheet.save(path, quality=90)


if __name__ == "__main__":
    for name, fn in (("A_solid_pill", option_a), ("B_category_headline", option_b), ("C_banner", option_c)):
        tiles = []
        for cat in CATS:
            im = fn(cat)
            tiles.append(im)
            im.convert("RGB").save(os.path.join(HERE, f"{name}_{pt.SHORT_CATEGORY[cat].split()[0].lower()}.jpg"), quality=90)
        grid_preview(tiles, os.path.join(HERE, f"{name}_GRID.jpg"))
        print("made", name)
