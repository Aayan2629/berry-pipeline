#!/usr/bin/env python3
"""
dashboard.py -- the one page you look at right before you post.

    python3 dashboard.py            build it and open it
    python3 dashboard.py --quiet    build it, don't open a browser

It also opens by itself at the end of a dry run:

    python3 publish_to_instagram.py --dry-run

WHAT IT ANSWERS

Three questions that used to need three different things:

  1. How many posts are due today?  Usually one. Sometimes two -- when a
     category from an earlier day still has a part sitting in the queue that
     the rest days never absorbed. The big number at the top is that count.
  2. What do those posts actually look like?  Every slide, in swipe order,
     read straight off disk, with the caption exactly as Instagram gets it.
  3. What do I type to send them?  The exact command for each one, with a
     copy button, in the order they should go out.

Nothing here publishes, uploads, or changes a single file in the queue. It
only reads. The command is printed for you to run yourself, on purpose --
a dashboard that could post would eventually post by accident.

HOW "DUE TODAY" IS WORKED OUT

publish_to_instagram.py owns the schedule (Monday tech, Thursday finance,
Saturday engineering) and the two-day overflow lookback. This file imports
both from it rather than keeping a second copy, so the dashboard can never
drift out of step with the thing that actually posts.

From that:

  * A scheduled day that has already passed and still has carousels waiting
    is OVERDUE -- every one of its parts is counted, because the rest days
    that were meant to absorb them have been and gone.
  * Today's own category counts ONE part, its next one. Any further parts
    are spillover, and land on the following days by design.

So "2 posts due" means: something is genuinely late, and today's post is
still to go out on top of it.
"""

import argparse
import html
import json
import os
import webbrowser
from datetime import datetime, timedelta

# Everything about the schedule comes from the publisher. One source of
# truth -- change the schedule there and this page follows.
import publish_to_instagram as pub

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dashboard.html")

# The same colours the slides themselves are drawn in, so a category reads
# the same here as it does in the post.
COLOURS = {
    "Business, Commerce, Marketing & Finance": "#8e2f52",
    "Technology, Data & AI": "#1d5c61",
    "Engineering": "#9a4a2c",
}
FALLBACK = "#8e2f52"


# ===========================================================================
# READING THE QUEUE
# ===========================================================================

def read_carousel(name):
    """One carousel folder -> everything the page needs to draw it.

    Returns None for anything that isn't a real carousel, so a stray folder
    or a half-finished build can never break the page.
    """
    folder = os.path.join(pub.QUEUE, name)
    if not os.path.isdir(folder):
        return None

    slides = sorted(f for f in os.listdir(folder)
                    if f.startswith("slide_") and f.lower().endswith(".jpg"))
    if not slides:
        return None

    caption = ""
    cap_path = os.path.join(folder, "caption.txt")
    if os.path.exists(cap_path):
        with open(cap_path, encoding="utf-8") as f:
            caption = f.read().strip()

    meta = {}
    meta_path = os.path.join(folder, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}

    return {
        "name": name,
        "category": meta.get("category", "Unknown"),
        "part": meta.get("part", 1),
        "slides": slides,
        "caption": caption,
        # Slide 1 is the cover, so the number of roles is one less than the
        # number of slides.
        "n_jobs": max(len(slides) - 1, 0),
        "built": datetime.fromtimestamp(os.path.getmtime(folder)),
    }


def everything_waiting():
    """Every carousel currently in the queue, by folder name."""
    if not os.path.isdir(pub.QUEUE):
        return {}
    out = {}
    for name in sorted(os.listdir(pub.QUEUE)):
        c = read_carousel(name)
        if c:
            out[name] = c
    return out


# ===========================================================================
# WHAT IS DUE
# ===========================================================================

def work_out_whats_due(queue, today=None):
    """Split the queue into: due now, spilling over, and not their day yet.

    THE RULE, in one sentence: a category's part 1 belongs on that category's
    day, part 2 on the day after, part 3 the day after that -- and anything
    whose day has arrived or gone by is due now.

    That single line covers both cases. On Thursday, Finance part 1 is
    today's post and part 2 is tomorrow's. On Friday, part 1 is a day late
    and part 2 has become today's post -- so Friday genuinely owes two, and
    the page says two.

    Walks the lookback window oldest day first, so the list comes out in the
    order the posts should actually go out: the late ones before today's.
    """
    today = today or datetime.now()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)
    due, spill = [], []
    claimed = set()

    # range(2, 1, 0) with the default lookback: the day before yesterday
    # first, today last.
    for back in range(pub.OVERFLOW_LOOKBACK_DAYS, -1, -1):
        day = today - timedelta(days=back)
        category = pub.SCHEDULE.get(day.weekday())
        if not category:
            continue                      # a rest day has nothing of its own

        # carousels_for() returns this category's folders, lowest part first,
        # which is the order they were meant to go out in.
        parts = [n for n in pub.carousels_for(category)
                 if n in queue and n not in claimed]

        for i, name in enumerate(parts):
            claimed.add(name)
            # Part i was meant for this category's day plus i days.
            meant_for = day + timedelta(days=i)
            late_by = (today - meant_for).days
            if late_by >= 0:
                due.append((queue[name], late_by, category, meant_for))
            else:
                spill.append((queue[name], -late_by))

    later = [c for name, c in queue.items() if name not in claimed]
    return due, spill, later


# ===========================================================================
# THE STATE OF THE ACCOUNT
# ===========================================================================

def account_notes():
    """The handful of things worth knowing before you post. Each is either a
    warning or None. Nothing here ever prints or embeds a token."""
    notes = []

    # When did anything last go out?
    try:
        history = pub.load_history()
        gap = pub.days_since_last_post(history)
        posts = len(history.get("posts", []))
    except Exception:
        gap, posts = None, 0

    if gap is not None and gap < 0:
        gap = 0                # a timestamp slightly ahead of the clock
    if gap is None:
        notes.append(("neutral", "Nothing has been posted yet."))
    elif gap == 0:
        notes.append(("good", "Something already went out today."))
    elif gap == 1:
        notes.append(("good", "Last post was yesterday."))
    elif gap >= 7:
        notes.append(("warn", f"Nothing has gone out for {gap} days."))
    else:
        notes.append(("neutral", f"Last post was {gap} days ago."))

    # Is the token about to die? This is the failure that quietly kills the
    # account, so it belongs on the page rather than in a script's output.
    try:
        env = pub.load_env()
        obtained = env.get("IG_TOKEN_OBTAINED")
        if obtained:
            age = (datetime.now() - datetime.fromisoformat(obtained)).days
            left = pub.TOKEN_LIFETIME_DAYS - age
            if left <= 0:
                notes.append(("warn", f"Your Instagram token expired "
                                      f"{-left} days ago. Nothing can post "
                                      f"until you replace it in .env."))
            elif age >= pub.WARN_TOKEN_AT_DAYS:
                notes.append(("warn", f"Token expires in {left} days."))
    except SystemExit:
        notes.append(("warn", "No .env file, so nothing can post."))
    except Exception:
        pass

    return notes, posts


# ===========================================================================
# THE PAGE
# ===========================================================================

def slide_strip(c):
    """The slides of one carousel, side by side, in swipe order."""
    out = []
    for i, s in enumerate(c["slides"]):
        src = f'queue_carousels/{c["name"]}/{s}'
        label = "cover" if i == 0 else str(i + 1)
        out.append(
            f'<figure><img src="{html.escape(src)}" loading="lazy" '
            f'alt="slide {i + 1}"><figcaption>{label}</figcaption></figure>')
    return "".join(out)


def post_card(c, late_by, meant_for, order, command):
    """One post that is due, as a card.

    late_by is how many days ago this one should have gone out, and meant_for
    is that day. 0 means it is today's post and nothing is wrong.
    """
    colour = COLOURS.get(c["category"], FALLBACK)

    if late_by > 0:
        day = pub.DAY_NAMES[meant_for.weekday()]
        days = "a day" if late_by == 1 else f"{late_by} days"
        flag = (f'<span class="flag late">{days} late &mdash; this was '
                f'{day}&rsquo;s post</span>')
    else:
        flag = '<span class="flag now">Today&rsquo;s post</span>'

    caption = html.escape(c["caption"])
    chars = len(c["caption"])

    return f"""
    <article class="post" style="--c:{colour}">
      <header>
        <span class="ord">{order}</span>
        <div class="who">
          <h2>{html.escape(c["category"])}</h2>
          <p>part {c["part"]} &middot; {c["n_jobs"]} role{"" if c["n_jobs"] == 1 else "s"}
             &middot; {len(c["slides"])} slides
             &middot; built {c["built"].strftime("%a %d %b")}</p>
        </div>
        {flag}
      </header>

      <div class="strip">{slide_strip(c)}</div>

      <details>
        <summary>Caption &mdash; {chars} characters</summary>
        <pre>{caption}</pre>
      </details>

      <div class="cmd">
        <code id="cmd{order}">{html.escape(command)}</code>
        <button type="button" onclick="copyCmd('cmd{order}', this)">Copy</button>
      </div>
    </article>"""


def small_card(c, note):
    colour = COLOURS.get(c["category"], FALLBACK)
    return f"""
      <li style="--c:{colour}">
        <img src="queue_carousels/{html.escape(c["name"])}/{html.escape(c["slides"][0])}"
             loading="lazy" alt="">
        <div>
          <b>{html.escape(c["category"])}</b>
          <span>part {c["part"]} &middot; {c["n_jobs"]} roles</span>
          <em>{html.escape(note)}</em>
        </div>
      </li>"""


def build(due, spill, later, notes, total_posts, now=None):
    # now is a parameter so the page can be built for a date other than today
    # -- which is the only way to check what a two-post day will look like
    # before one actually happens.
    now = now or datetime.now()
    today_name = pub.DAY_NAMES[now.weekday()]
    todays_category = pub.SCHEDULE.get(now.weekday())

    n = len(due)

    # The headline. This is the whole reason the page exists, so it says the
    # number in words as well as digits.
    if n == 0:
        if todays_category:
            headline = f"{today_name} is {todays_category} day"
            sub = "but there is nothing waiting in the queue for it."
        else:
            headline = f"{today_name} is a rest day"
            sub = "and nothing is left over. Nothing to do."
    elif n == 1:
        c, late_by, _, _ = due[0]
        headline = "1 post due today"
        if late_by:
            sub = (f"{html.escape(c['category'])} &mdash; and it is "
                   f"{late_by} day{'' if late_by == 1 else 's'} late.")
        else:
            sub = (f"{html.escape(c['category'])} &mdash; check it below, "
                   f"then run the command.")
    else:
        headline = f"{n} posts due today"
        late = sum(1 for _, late_by, _, _ in due if late_by > 0)
        if late:
            sub = (f"{late} of them {'is' if late == 1 else 'are'} late. "
                   f"Post them oldest first, in the order below.")
        else:
            sub = "Post them in the order below."

    cards = []
    for i, (c, late_by, category, meant_for) in enumerate(due, start=1):
        # The first one is whatever the publisher would pick on its own, so
        # the bare command is enough. After that, name the carousel, because
        # the bare command would just pick the first one again.
        if i == 1:
            command = "python3 publish_to_instagram.py"
        else:
            command = f"python3 publish_to_instagram.py {c['name']}"
        cards.append(post_card(c, late_by, meant_for, i, command))

    rest = []
    for c, offset in spill:
        when = "tomorrow" if offset == 1 else f"in {offset} days"
        rest.append(small_card(c, f"spills over to {when}"))
    for c in later:
        day = {v: k for k, v in pub.SCHEDULE.items()}.get(c["category"])
        when = pub.DAY_NAMES[day] if day is not None else "no scheduled day"
        rest.append(small_card(c, f"waits for {when}"))

    rest_block = ""
    if rest:
        rest_block = f"""
    <section class="rest">
      <h3>Also in the queue &mdash; not due today</h3>
      <ul>{"".join(rest)}</ul>
    </section>"""

    notes_block = "".join(
        f'<li class="{kind}">{html.escape(text)}</li>' for kind, text in notes)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>berry &mdash; posting dashboard</title>
<style>
  :root {{
    --ink: #17151a; --dim: #6b6470; --line: #e6e1e8;
    --bg: #faf7fb; --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 40px 24px 80px; }}

  /* ---- the headline -------------------------------------------------- */
  .top {{ margin-bottom: 8px; }}
  .top .date {{
    font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    color: var(--dim); margin: 0 0 10px;
  }}
  .top h1 {{ margin: 0; font-size: 40px; letter-spacing: -.02em; line-height: 1.1; }}
  .top p {{ margin: 8px 0 0; color: var(--dim); font-size: 16px; }}

  .notes {{ list-style: none; padding: 0; margin: 22px 0 36px;
            display: flex; flex-wrap: wrap; gap: 8px; }}
  .notes li {{
    font-size: 13px; padding: 5px 11px; border-radius: 999px;
    border: 1px solid var(--line); background: var(--card); color: var(--dim);
  }}
  .notes li.warn {{ border-color: #f0c2ae; background: #fff5f0; color: #9a3a12; }}
  .notes li.good {{ border-color: #c4e2cd; background: #f3fbf5; color: #2b6b41; }}

  /* ---- a post that is due -------------------------------------------- */
  .post {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 16px; padding: 20px; margin-bottom: 20px;
    border-left: 4px solid var(--c);
  }}
  .post header {{ display: flex; align-items: flex-start; gap: 14px; }}
  .post .ord {{
    flex: none; width: 30px; height: 30px; border-radius: 50%;
    background: var(--c); color: #fff; font-weight: 700; font-size: 14px;
    display: grid; place-items: center;
  }}
  .post .who {{ flex: 1; min-width: 0; }}
  .post h2 {{ margin: 2px 0 0; font-size: 19px; letter-spacing: -.01em; }}
  .post .who p {{ margin: 3px 0 0; color: var(--dim); font-size: 13px; }}
  .flag {{
    flex: none; font-size: 12px; font-weight: 600; padding: 5px 10px;
    border-radius: 999px; white-space: nowrap;
  }}
  .flag.now {{ background: #eef4ff; color: #2c4f9e; }}
  .flag.late {{ background: #fdeeea; color: #a3391a; }}

  /* The slides scroll sideways in their own box -- the page itself must
     never scroll sideways. */
  .strip {{
    display: flex; gap: 10px; overflow-x: auto; padding: 18px 2px 6px;
    scroll-snap-type: x proximity;
  }}
  .strip figure {{ margin: 0; flex: none; scroll-snap-align: start; }}
  .strip img {{
    display: block; width: 168px; height: 168px; object-fit: cover;
    border-radius: 10px; border: 1px solid var(--line); background: #eee;
  }}
  .strip figcaption {{
    font-size: 11px; color: var(--dim); text-align: center; margin-top: 5px;
  }}

  details {{ margin-top: 4px; }}
  summary {{ cursor: pointer; font-size: 13px; color: var(--dim); }}
  details pre {{
    white-space: pre-wrap; word-break: break-word; font-size: 13px;
    background: #f6f3f7; border: 1px solid var(--line); border-radius: 10px;
    padding: 14px; margin: 10px 0 0; max-height: 320px; overflow: auto;
  }}

  .cmd {{
    display: flex; align-items: center; gap: 10px; margin-top: 16px;
    background: #17151a; border-radius: 10px; padding: 11px 12px;
  }}
  .cmd code {{
    flex: 1; min-width: 0; overflow-x: auto; white-space: nowrap;
    color: #eae6ee; font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .cmd button {{
    flex: none; border: 0; border-radius: 7px; padding: 6px 13px;
    background: #3b3641; color: #fff; font-size: 12px; font-weight: 600;
    cursor: pointer;
  }}
  .cmd button:hover {{ background: #4d4754; }}

  /* ---- the rest of the queue ----------------------------------------- */
  .rest {{ margin-top: 46px; }}
  .rest h3 {{
    font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    color: var(--dim); margin: 0 0 14px; font-weight: 600;
  }}
  .rest ul {{
    list-style: none; padding: 0; margin: 0;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 12px;
  }}
  .rest li {{
    display: flex; gap: 12px; align-items: center; background: var(--card);
    border: 1px solid var(--line); border-left: 3px solid var(--c);
    border-radius: 12px; padding: 11px;
  }}
  .rest img {{
    width: 52px; height: 52px; object-fit: cover; border-radius: 8px;
    flex: none; background: #eee;
  }}
  .rest b {{ display: block; font-size: 13px; }}
  .rest span, .rest em {{ display: block; font-size: 12px; color: var(--dim); }}
  .rest em {{ font-style: normal; margin-top: 2px; opacity: .85; }}

  footer {{
    margin-top: 54px; padding-top: 20px; border-top: 1px solid var(--line);
    color: var(--dim); font-size: 12.5px;
  }}
  footer code {{ background: #efeaf1; padding: 2px 6px; border-radius: 5px; }}

  @media (max-width: 640px) {{
    .top h1 {{ font-size: 30px; }}
    .post header {{ flex-wrap: wrap; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <p class="date">{today_name} {now.strftime("%d %B %Y")} &middot; {now.strftime("%H:%M")}</p>
    <h1>{headline}</h1>
    <p>{sub}</p>
  </div>

  <ul class="notes">
    {notes_block}
    <li>{total_posts} post{"" if total_posts == 1 else "s"} published all time</li>
  </ul>

  {"".join(cards)}
  {rest_block}

  <footer>
    Read-only. Nothing on this page can post &mdash; run the command yourself.<br>
    Rebuild it any time with <code>python3 dashboard.py</code>. It also opens
    on its own at the end of <code>python3 publish_to_instagram.py --dry-run</code>.
  </footer>

</div>
<script>
// Copy a command. navigator.clipboard is blocked in some browsers when the
// page is opened straight off disk, so fall back to the old textarea trick,
// which works everywhere.
function copyCmd(id, btn) {{
  var text = document.getElementById(id).textContent;
  var done = function () {{
    var was = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(function () {{ btn.textContent = was; }}, 1400);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(done, function () {{ fallback(text, done); }});
  }} else {{
    fallback(text, done);
  }}
}}
function fallback(text, done) {{
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {{ document.execCommand('copy'); done(); }} catch (e) {{}}
  document.body.removeChild(ta);
}}
</script>
</body>
</html>
"""


# ===========================================================================

def build_and_open(open_browser=True):
    """Write dashboard.html and (usually) open it. Returns how many posts
    are due, so the caller can print a one-line summary."""
    queue = everything_waiting()
    due, spill, later = work_out_whats_due(queue)
    notes, total_posts = account_notes()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(due, spill, later, notes, total_posts))

    if open_browser:
        webbrowser.open("file://" + OUT)
    return len(due)


def main():
    ap = argparse.ArgumentParser(description="The posting dashboard.")
    ap.add_argument("--quiet", action="store_true",
                    help="build it without opening a browser")
    args = ap.parse_args()

    n = build_and_open(open_browser=not args.quiet)
    print(f"{n} post(s) due today")
    print(f"Wrote: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
