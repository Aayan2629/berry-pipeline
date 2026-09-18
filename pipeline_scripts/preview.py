#!/usr/bin/env python3
"""
preview.py -- look at everything waiting in the queue before it goes out.

Builds preview.html next to this script and opens it. Every carousel in
queue_carousels/ is shown as its actual slides, side by side in swipe order,
with the caption exactly as Instagram would receive it.

    python3 preview.py

Nothing is published, nothing is uploaded, nothing is changed. The page reads
the JPEGs straight off disk, so it always shows the real thing rather than a
mock-up of it.
"""

import html
import json
import os
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "queue_carousels")
OUT = os.path.join(HERE, "preview.html")

# The same four colours the slides themselves use, so a carousel's strip in
# the preview matches the post it will become.
COLOURS = {
    "Business, Commerce, Marketing & Finance": "#8e2f52",
    "Technology, Data & AI": "#1d5c61",
    "Engineering": "#9a4a2c",
}
FALLBACK = "#8e2f52"

# Monday is 0. Mirrors SCHEDULE in publish_to_instagram.py.
DAY_OF = {
    "Technology, Data & AI": "Monday",
    "Business, Commerce, Marketing & Finance": "Thursday",
    "Engineering": "Saturday",
}


def read_carousels():
    if not os.path.isdir(QUEUE):
        return []
    out = []
    for name in sorted(os.listdir(QUEUE)):
        d = os.path.join(QUEUE, name)
        if not os.path.isdir(d):
            continue
        slides = sorted(f for f in os.listdir(d) if f.startswith("slide_")
                        and f.endswith(".jpg"))
        if not slides:
            continue
        caption = ""
        cap_path = os.path.join(d, "caption.txt")
        if os.path.exists(cap_path):
            with open(cap_path, encoding="utf-8") as f:
                caption = f.read().strip()
        meta = {}
        meta_path = os.path.join(d, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except ValueError:
                pass
        out.append({
            "name": name,
            "slides": slides,
            "caption": caption,
            "category": meta.get("category", ""),
            "part": meta.get("part", 1),
            "n_jobs": len(slides) - 1,      # slide 1 is the cover
        })
    return out


def build(carousels):
    total_posts = len(carousels)
    total_roles = sum(c["n_jobs"] for c in carousels)

    cards = []
    for c in carousels:
        colour = COLOURS.get(c["category"], FALLBACK)
        day = DAY_OF.get(c["category"], "")
        imgs = "".join(
            f'<figure><img src="queue_carousels/{html.escape(c["name"])}/'
            f'{html.escape(s)}" alt="slide {i + 1}" loading="lazy">'
            f'<figcaption>{"cover" if i == 0 else i + 1}</figcaption></figure>'
            for i, s in enumerate(c["slides"]))

        cards.append(f"""
    <article class="post" style="--c:{colour}">
      <header>
        <div class="meta">
          <h2>{html.escape(c["category"] or c["name"])}</h2>
          <div class="sub">
            <span class="dot"></span>
            <span>{c["n_jobs"]} internship{"s" if c["n_jobs"] != 1 else ""}</span>
            <span>&middot;</span>
            <span>{len(c["slides"])} slides</span>
            {f'<span>&middot;</span><span>{day}s</span>' if day else ""}
          </div>
        </div>
        <code class="folder">{html.escape(c["name"])}</code>
      </header>
      <div class="strip">{imgs}</div>
      <details>
        <summary>Caption &mdash; {len(c["caption"])} characters
          <span class="limit">(Instagram allows 2,200)</span></summary>
        <pre>{html.escape(c["caption"])}</pre>
      </details>
      <div class="cmd">
        <span>Publish this one:</span>
        <code>python3 publish_to_instagram.py {html.escape(c["name"])}</code>
      </div>
    </article>""")

    empty = ("<p class='empty'>Nothing is waiting in the queue. Run "
             "<code>python3 build_carousels.py --rebuild</code> first.</p>")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Queue preview &mdash; berry.internships.syd</title>
<style>
  :root {{
    --paper:#f7f4f6; --card:#fff; --ink:#1e1720; --soft:#4c4150;
    --muted:#7d7183; --rule:#ded4dd;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --paper:#141016; --card:#1d1822; --ink:#f0e9f0; --soft:#c3b7c6;
      --muted:#948a99; --rule:#3a3243;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--paper); color:var(--ink);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:40px 22px 80px; }}
  header.top {{ border-bottom:2px solid var(--ink); padding-bottom:20px;
                margin-bottom:34px; }}
  header.top h1 {{ margin:0 0 6px; font-size:1.9rem; letter-spacing:-.02em; }}
  header.top p {{ margin:0; color:var(--soft); }}
  .tally {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }}
  .tally span {{
    font:600 .76rem/1 ui-monospace,monospace; letter-spacing:.03em;
    padding:7px 12px; border:1px solid var(--rule); border-radius:999px;
    background:var(--card); color:var(--soft);
  }}
  .post {{
    background:var(--card); border:1px solid var(--rule);
    border-top:4px solid var(--c); border-radius:4px;
    padding:20px 22px 22px; margin-bottom:22px;
  }}
  .post header {{
    display:flex; justify-content:space-between; align-items:flex-start;
    gap:16px; flex-wrap:wrap; margin-bottom:16px;
  }}
  .post h2 {{ margin:0; font-size:1.12rem; color:var(--c);
              letter-spacing:-.01em; }}
  .sub {{ display:flex; gap:7px; align-items:center; color:var(--muted);
          font-size:.85rem; margin-top:4px; flex-wrap:wrap; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:var(--c);
          display:block; }}
  .folder, .cmd code {{
    font:.75rem/1.5 ui-monospace,monospace; color:var(--muted);
    background:var(--paper); border:1px solid var(--rule);
    border-radius:4px; padding:4px 8px; white-space:nowrap;
  }}
  .strip {{
    display:flex; gap:12px; overflow-x:auto; padding-bottom:10px;
    scroll-snap-type:x mandatory;
  }}
  .strip figure {{ margin:0; flex:none; scroll-snap-align:start; }}
  .strip img {{
    width:250px; height:250px; display:block; border-radius:3px;
    border:1px solid var(--rule); background:var(--paper);
  }}
  .strip figcaption {{
    font:600 .68rem/1 ui-monospace,monospace; color:var(--muted);
    text-align:center; padding-top:7px; letter-spacing:.08em;
    text-transform:uppercase;
  }}
  details {{ margin-top:16px; border-top:1px solid var(--rule);
             padding-top:14px; }}
  summary {{ cursor:pointer; font-weight:600; font-size:.88rem;
             color:var(--soft); }}
  summary::marker {{ color:var(--c); }}
  .limit {{ font-weight:400; color:var(--muted); }}
  pre {{
    white-space:pre-wrap; word-break:break-word; margin:12px 0 0;
    font:.86rem/1.7 -apple-system,BlinkMacSystemFont,sans-serif;
    background:var(--paper); border:1px solid var(--rule);
    border-radius:4px; padding:15px 17px; color:var(--ink);
  }}
  .cmd {{ display:flex; gap:9px; align-items:center; margin-top:14px;
          flex-wrap:wrap; font-size:.82rem; color:var(--muted); }}
  .empty {{ color:var(--muted); }}
  footer {{ margin-top:36px; color:var(--muted); font-size:.85rem; }}
</style></head><body>
<div class="wrap">
  <header class="top">
    <h1>Queue preview</h1>
    <p>Everything waiting to go out on <strong>@berry.internships.syd</strong>.
       Nothing here has been published.</p>
    <div class="tally">
      <span>{total_posts} post{"s" if total_posts != 1 else ""} queued</span>
      <span>{total_roles} internships</span>
      <span>0 published so far</span>
    </div>
  </header>
  {"".join(cards) if cards else empty}
  <footer>Slides are read straight off disk &mdash; rerun
    <code>python3 preview.py</code> after any rebuild to refresh this page.</footer>
</div></body></html>"""


def main():
    carousels = read_carousels()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(carousels))
    print(f"{len(carousels)} carousel(s), "
          f"{sum(c['n_jobs'] for c in carousels)} internships")
    print(f"Wrote: {OUT}")
    webbrowser.open("file://" + OUT)


if __name__ == "__main__":
    main()
