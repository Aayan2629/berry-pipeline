"""
dashboard_map.py -- the "Map" section of the dashboard.

    berry  ──►  category  ──►  every job waiting to be posted in it

A node graph like a mission-control screen: the account on the left, the five
categories in the middle (with how many roles each has queued and the date it
next posts), and when you tap a category its jobs fan out on the right. The
panel on the far right shows whatever you tapped -- for a job, the actual
slide it will go out on.

dashboard.py calls map_block(queue) and drops the result into the page. It
only READS the queue (same as the rest of the dashboard). Nothing here posts.

HOW IT'S BUILT
  Python gathers the data (categories, parts, jobs, dates) into one JSON blob.
  The browser draws it: the boxes are normal HTML, the curved lines between
  them are an SVG drawn by JavaScript AFTER the boxes are laid out, because
  only then do we know where each box actually is on screen.
  (Like computing coordinates first and then calling a draw function in C.)
"""

import json
import os
import re
from datetime import datetime, timedelta

import publish_to_instagram as pub

HERE = os.path.dirname(os.path.abspath(__file__))

# Same colours as the slides / the rest of the dashboard.
COLOURS = {
    "Technology, Data & AI": "#1d8a93",
    "Business, Commerce, Marketing & Finance": "#c0386e",
    "Engineering": "#c8653a",
    "Architecture": "#7c86d6",
    "Medicine & Health": "#3aa877",
}
SHORT = {
    "Technology, Data & AI": "Tech & Data",
    "Business, Commerce, Marketing & Finance": "Business",
    "Engineering": "Engineering",
    "Architecture": "Architecture",
    "Medicine & Health": "Medicine",
}


def _jobs_from_caption(caption):
    """Pull (title, company, link) for each slide out of caption.txt.

    Each job in the caption is a little block:
        2️⃣ Architectural Graduate
        🏢 Baxter Richards Pty Ltd        (sometimes missing)
        🔗 seek.com.au/job/94870051
    Blocks are separated by blank lines, like paragraphs. We keep only the
    blocks whose last line is a 🔗 link -- that's what marks a job.
    """
    jobs = []
    for block in re.split(r"\n\s*\n", caption or ""):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines or not lines[-1].startswith("🔗"):
            continue
        # first line is "<keycap emoji> <title>" -- drop the emoji
        title = lines[0].split(" ", 1)[1] if " " in lines[0] else lines[0]
        company = ""
        for l in lines[1:-1]:
            if l.startswith("🏢"):
                company = l.replace("🏢", "").strip().lstrip("@")
        link = lines[-1].replace("🔗", "").strip()
        jobs.append({"title": title, "company": company,
                     "url": link if link.startswith("http") else "https://" + link})
    return jobs


def _next_date(category, today, part_index):
    """When part N of this category goes out: its weekday on/after today,
    not before the category's start date, plus one day per extra part."""
    day = {v: k for k, v in pub.SCHEDULE.items()}.get(category)
    if day is None:
        return None
    # Already due? Its day was today or within the overflow lookback and it
    # still has parts waiting -> it goes out now (same rule the publisher uses).
    for back in range(pub.OVERFLOW_LOOKBACK_DAYS, -1, -1):
        d0 = today - timedelta(days=back)
        if pub.category_on(d0) == category:
            return max(d0 + timedelta(days=part_index), today)
    d = today
    start = getattr(pub, "SCHEDULE_START", {}).get(category)
    for _ in range(14):
        ok_start = not start or d.strftime("%Y-%m-%d") >= start
        if d.weekday() == day and ok_start:
            break
        d += timedelta(days=1)
    return d + timedelta(days=part_index)


def map_data(queue, now=None):
    now = (now or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    cats = []
    # schedule order: Mon, Wed, Thu, Sat, Sun
    for weekday in sorted(pub.SCHEDULE):
        category = pub.SCHEDULE[weekday]
        parts = [queue[n] for n in pub.carousels_for(category) if n in queue]
        jobs, posts = [], []
        for i, c in enumerate(parts):
            when = _next_date(category, now, i)
            when_s = ("today" if when == now else when.strftime("%a %-d %b")) if when else "?"
            posts.append({"name": c["name"], "part": c["part"], "when": when_s,
                          "cover": f'queue_carousels/{c["name"]}/{c["slides"][0]}',
                          "n": c["n_jobs"]})
            job_slides = [s for s in c["slides"] if "_cover" not in s and "_end" not in s]
            for j, info in enumerate(_jobs_from_caption(c["caption"])):
                slide = job_slides[j] if j < len(job_slides) else c["slides"][0]
                jobs.append({**info, "part": c["part"], "slide_no": j + 2,
                             "when": when_s,
                             "img": f'queue_carousels/{c["name"]}/{slide}'})
        cats.append({
            "name": category, "short": SHORT.get(category, category),
            "colour": COLOURS.get(category, "#c9a24a"),
            "day": pub.DAY_NAMES[weekday],
            "next": posts[0]["when"] if posts else "nothing queued",
            "posts": posts, "jobs": jobs,
        })
    return {"total": sum(len(c["jobs"]) for c in cats), "cats": cats}


# ---------------------------------------------------------------------------
# The HTML. A plain string (not an f-string) so the CSS/JS braces don't need
# doubling; the data goes in by .replace() at the end.
# ---------------------------------------------------------------------------
TEMPLATE = r"""
<section class="bmap" id="map">
  <div class="bmap-head">
    <h2>Map <span>every job waiting, by category &mdash; tap to explore</span></h2>
  </div>
  <div class="bmap-space">
    <div class="bmap-canvas" id="bmapCanvas">
      <svg class="bmap-lines" id="bmapLines"></svg>
      <div class="bmap-hub" id="bmapHub">
        <div class="orbit"></div><div class="orb"></div>
        <b>berry</b><small><span id="bmapTotal"></span> roles queued</small>
      </div>
      <div class="bmap-cats" id="bmapCats"></div>
      <div class="bmap-fan" id="bmapFan"></div>
    </div>
    <aside class="bmap-panel" id="bmapPanel"></aside>
  </div>
</section>

<style>
.bmap { margin: 46px 0 10px; }
.bmap-head h2 { font-size: 19px; margin: 0 0 14px; letter-spacing: -.01em; }
.bmap-head h2 span { font-size: 14px; font-weight: 500; color: var(--dim); margin-left: 8px; }
/* The map is always "space" dark, in light mode too -- like the reference. */
.bmap-space {
  --gold: #e3bd6d;
  display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 14px;
  padding: 14px; border-radius: 22px; color: #eee8dc;
  background: radial-gradient(1200px 500px at 10% 50%, #1d2a2c 0%, #0d1214 55%, #080b0c 100%);
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: 0 30px 60px rgba(0,0,0,.25);
}
.bmap-canvas { position: relative; height: 620px; overflow: hidden; }
.bmap-lines { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }

/* the hub */
.bmap-hub {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  width: 170px; height: 170px; border-radius: 50%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: radial-gradient(circle, rgba(255,255,255,.05), rgba(255,255,255,0) 70%);
  border: 1px solid rgba(255,255,255,.07); text-align: center;
}
.bmap-hub .orbit {
  position: absolute; inset: 26px; border-radius: 50%;
  border: 1px dashed rgba(227,189,109,.35); animation: bspin 40s linear infinite;
}
.bmap-hub .orb {
  width: 58px; height: 58px; border-radius: 50%; margin-bottom: 10px;
  background: radial-gradient(circle at 35% 30%, #fff 0%, #d9c3ff 18%, #8e6bd8 60%, #3b2a66 100%);
  box-shadow: 0 0 30px rgba(160,120,255,.65), 0 0 70px rgba(160,120,255,.25);
}
.bmap-hub b { font-size: 17px; letter-spacing: .02em; }
.bmap-hub small { font-size: 11.5px; color: rgba(238,232,220,.6); }
@keyframes bspin { to { transform: rotate(360deg); } }

/* the categories */
.bmap-cats {
  position: absolute; left: 205px; top: 0; bottom: 0; width: 155px;
  display: flex; flex-direction: column; justify-content: center; gap: 14px;
}
.bmap-cat {
  all: unset; box-sizing: border-box; cursor: pointer; width: 100%;
  padding: 10px 12px; border-radius: 12px;
  background: linear-gradient(145deg, rgba(255,255,255,.07), rgba(255,255,255,.02));
  border: 1px solid rgba(255,255,255,.10);
  transition: all .25s ease;
}
.bmap-cat:hover { border-color: rgba(255,255,255,.25); }
.bmap-cat .n { font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.bmap-cat .n i { width: 9px; height: 9px; border-radius: 50%; background: var(--c);
                 box-shadow: 0 0 10px var(--c); }
.bmap-cat .l { font-size: 12px; color: rgba(238,232,220,.75); }
.bmap-cat .d { white-space: nowrap; font-size: 10.5px; color: rgba(238,232,220,.45); margin-top: 2px; }
.bmap-cat.on {
  border-color: var(--gold);
  box-shadow: 0 0 0 1px rgba(227,189,109,.35), 0 0 26px rgba(227,189,109,.22);
  background: linear-gradient(145deg, rgba(227,189,109,.16), rgba(227,189,109,.04));
}

/* the fan of jobs */
.bmap-fan { position: absolute; left: 385px; right: 0; top: 0; bottom: 0; }
.bmap-job {
  all: unset; box-sizing: border-box; position: absolute; cursor: pointer;
  width: 210px; padding: 3px 8px 4px; border-radius: 8px;
  transition: background .2s ease; opacity: 0; animation: bin .45s ease forwards;
}
.bmap-job:hover, .bmap-job.on { background: rgba(255,255,255,.07); }
.bmap-job .t { display: block; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bmap-job .m { display: flex; gap: 6px; align-items: center; font-size: 10px; color: rgba(238,232,220,.5);
               white-space: nowrap; min-width: 0; }
.bmap-job .m .co { overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1; }
.bmap-job .m i { flex: none; width: 18px; height: 3px; border-radius: 2px; background: var(--c); }
@keyframes bin { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: none; } }
.bmap-post {
  all: unset; box-sizing: border-box; position: absolute; cursor: pointer; width: 190px;
  padding: 5px 10px; border-radius: 9px; font-size: 12px; font-weight: 700;
  background: linear-gradient(145deg, rgba(255,255,255,.09), rgba(255,255,255,.03));
  border: 1px solid rgba(255,255,255,.14); opacity: 0; animation: bin .45s ease forwards;
}
.bmap-post small { display: block; font-weight: 500; font-size: 10.5px; color: rgba(238,232,220,.55); }
.bmap-post i { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
               background: var(--c); box-shadow: 0 0 8px var(--c); margin-right: 6px; }
.bmap-post:hover, .bmap-post.on { border-color: var(--gold); }
.bmap-empty { position: absolute; left: 40px; top: 50%; color: rgba(238,232,220,.5); font-size: 13px; }

/* the panel */
.bmap-panel {
  border-radius: 18px; padding: 18px;
  background: linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.025));
  border: 1px solid rgba(255,255,255,.10);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  min-width: 0; max-height: 620px; overflow-y: auto;
}
.bmap-panel .kick { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--gold); }
.bmap-panel h3 { margin: 6px 0 4px; font-size: 20px; line-height: 1.25; }
.bmap-panel .sub { font-size: 13px; color: rgba(238,232,220,.6); margin: 0 0 14px; }
.bmap-panel .pill { display: inline-block; font-size: 11px; padding: 2px 9px; border-radius: 999px;
                    border: 1px solid rgba(58,168,119,.6); color: #8fe0b7; background: rgba(58,168,119,.12); }
.bmap-panel img { display: block; width: 100%; border-radius: 12px; margin: 12px 0;
                  border: 1px solid rgba(255,255,255,.12); background: #111; }
.bmap-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
.bmap-stats div { padding: 12px; border-radius: 12px; background: rgba(255,255,255,.04);
                  border: 1px solid rgba(255,255,255,.08); }
.bmap-stats b { display: block; font-size: 24px; }
.bmap-stats span { font-size: 11.5px; color: rgba(238,232,220,.55); }
.bmap-panel a.go { display: inline-flex; gap: 6px; align-items: center; font-size: 13px;
                   color: #111; background: var(--gold); padding: 8px 14px; border-radius: 999px;
                   text-decoration: none; font-weight: 600; }
.bmap-posts { list-style: none; margin: 8px 0 0; padding: 0; }
.bmap-posts li { display: flex; gap: 10px; align-items: center; padding: 8px 0;
                 border-top: 1px solid rgba(255,255,255,.07); font-size: 12.5px; }
.bmap-posts img { width: 44px; height: 44px; margin: 0; border-radius: 8px; flex: none; }
.bmap-posts span { color: rgba(238,232,220,.55); display: block; font-size: 11.5px; }

/* phones: stack it -- hub + categories as a row, jobs as a list */
@media (max-width: 860px) {
  .bmap-space { grid-template-columns: 1fr; }
  .bmap-canvas { height: auto; }
  .bmap-panel { max-height: none; }
  .bmap-lines, .bmap-hub { display: none; }
  .bmap-cats { position: static; width: auto; flex-direction: row; overflow-x: auto;
               padding-bottom: 6px; }
  .bmap-cat { min-width: 130px; }
  .bmap-fan { position: static; margin-top: 12px; }
  .bmap-job { position: static; display: block; width: auto; margin: 2px 0 2px 16px; }
  .bmap-post { position: static; display: block; width: auto; margin: 12px 0 4px; }
}
</style>

<script>
(function () {
  var DATA = __MAP_DATA__;
  var canvas = document.getElementById('bmapCanvas');
  var svg = document.getElementById('bmapLines');
  var catsEl = document.getElementById('bmapCats');
  var fan = document.getElementById('bmapFan');
  var panel = document.getElementById('bmapPanel');
  var hub = document.getElementById('bmapHub');
  document.getElementById('bmapTotal').textContent = DATA.total;
  var current = 0;

  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  // ---- category buttons -------------------------------------------------
  DATA.cats.forEach(function (c, i) {
    var b = document.createElement('button');
    b.className = 'bmap-cat'; b.style.setProperty('--c', c.colour);
    b.innerHTML = '<div class="n"><i></i>' + c.jobs.length + '</div>' +
                  '<div class="l">' + esc(c.short) + '</div>' +
                  '<div class="d">' + esc(c.day) + ' &middot; ' + esc(c.next) + '</div>';
    b.onclick = function () { select(i); };
    catsEl.appendChild(b);
  });
  // start on whichever category posts soonest and has jobs
  var first = DATA.cats.findIndex(function (c) { return c.jobs.length; });
  current = first < 0 ? 0 : first;

  // ---- one curved line from a to b (points relative to the canvas) -------
  function curve(a, b, colour, width, glow) {
    var mx = (a.x + b.x) / 2;
    var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'M' + a.x + ',' + a.y + ' C' + mx + ',' + a.y + ' ' + mx + ',' + b.y + ' ' + b.x + ',' + b.y);
    p.setAttribute('fill', 'none'); p.setAttribute('stroke', colour);
    p.setAttribute('stroke-width', width); p.setAttribute('stroke-linecap', 'round');
    if (glow) p.setAttribute('filter', 'drop-shadow(0 0 4px ' + colour + ')');
    svg.appendChild(p);
    var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('cx', b.x); dot.setAttribute('cy', b.y); dot.setAttribute('r', 2.6);
    dot.setAttribute('fill', colour); svg.appendChild(dot);
  }
  function edge(el, side) {                 // a point on the left/right edge of a box
    var r = el.getBoundingClientRect(), c = canvas.getBoundingClientRect();
    return { x: (side === 'right' ? r.right : r.left) - c.left, y: r.top + r.height / 2 - c.top };
  }

  // ---- the fan: the category's POSTS (one per date), each with its jobs ---
  // Rows top to bottom: [post header, its jobs..., next post header, ...],
  // all placed on an arc that bulges out in the middle.
  function layoutFan(c) {
    fan.innerHTML = '';
    if (!c.posts.length) {
      fan.innerHTML = '<div class="bmap-empty">Nothing queued for ' + esc(c.short) + ' right now.</div>';
      return;
    }
    var rows = [];
    c.posts.forEach(function (p) {
      rows.push({ kind: 'post', p: p });
      c.jobs.filter(function (j) { return j.part === p.part; })
            .forEach(function (j) { rows.push({ kind: 'job', j: j, p: p }); });
    });
    var H = canvas.clientHeight, n = rows.length;
    var top = 20, bottom = H - 34, span = bottom - top;
    var postX = 10;
    rows.forEach(function (r, k) {
      var t = n === 1 ? 0.5 : k / (n - 1);
      var y = top + t * span;
      var bulge = 1 - Math.pow(2 * t - 1, 2);
      var x = r.kind === 'post' ? 10 + bulge * 45           // posts follow the arc
                                : postX + 28 + bulge * 12;   // jobs hang under their post
      var b = document.createElement('button');
      b.style.setProperty('--c', c.colour);
      b.style.left = x + 'px'; b.style.top = (y - 15) + 'px';
      b.style.animationDelay = (k * 25) + 'ms';
      if (r.kind === 'post') {
        b.className = 'bmap-post';
        b.innerHTML = '<i></i>' + esc(r.p.when === 'today' ? 'Today' : r.p.when) +
                      '<small>' + (c.posts.length > 1 ? 'part ' + r.p.part + ' &middot; ' : '') +
                      r.p.n + ' role' + (r.p.n === 1 ? '' : 's') + '</small>';
        b.onclick = function () { showPost(c, r.p, b); };
        postX = x;
      } else {
        b.className = 'bmap-job';
        b.dataset.parent = r.p.part;
        b.innerHTML = '<span class="t">' + esc(r.j.title) + '</span>' +
                      '<span class="m"><span class="co">' + esc(r.j.company || 'Company not listed') +
                      '</span><i></i></span>';
        b.onclick = function () { showJob(c, r.j, b); };
      }
      fan.appendChild(b);
    });
  }

  function draw() {
    svg.innerHTML = '';
    if (getComputedStyle(svg).display === 'none') return;   // phone layout
    var h = edge(hub, 'right');
    Array.prototype.forEach.call(catsEl.children, function (el, i) {
      var on = i === current;
      curve(h, edge(el, 'left'), on ? '#e3bd6d' : 'rgba(238,232,220,.22)', on ? 2 : 1.2, on);
    });
    var from = edge(catsEl.children[current], 'right');
    var colour = DATA.cats[current].colour;
    var posts = {};
    fan.querySelectorAll('.bmap-post').forEach(function (el, i) {
      posts[DATA.cats[current].posts[i].part] = el;
      curve(from, edge(el, 'left'), '#e3bd6d', 1.6, true);    // category -> each date
    });
    fan.querySelectorAll('.bmap-job').forEach(function (el) {
      var p = posts[el.dataset.parent];
      if (!p) return;
      var a = edge(p, 'left'); a.x += 14;                      // drop down from the post node
      var r = p.getBoundingClientRect(), cr = canvas.getBoundingClientRect();
      a.y = r.bottom - cr.top;
      var b = edge(el, 'left');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M' + a.x + ',' + a.y + ' C' + a.x + ',' + b.y + ' ' + a.x + ',' + b.y + ' ' + b.x + ',' + b.y);
      path.setAttribute('fill', 'none'); path.setAttribute('stroke', colour);
      path.setAttribute('stroke-width', 1.1); path.setAttribute('opacity', .8);
      svg.appendChild(path);
    });
  }

  // ---- the panel ---------------------------------------------------------
  function showCat(c) {
    var posts = c.posts.map(function (p) {
      return '<li><img src="' + esc(p.cover) + '" alt=""><div>' + (p.when === 'today' ? 'Today' : esc(p.when)) +
             '<span>' + p.n + ' role' + (p.n === 1 ? '' : 's') + '</span></div></li>';
    }).join('');
    panel.innerHTML =
      '<div class="kick">' + esc(c.day) + '</div>' +
      '<h3>' + esc(c.name) + '</h3>' +
      '<p class="sub">' + (c.posts.length ? 'Next post ' + esc(c.next) : 'Nothing queued') + '</p>' +
      '<div class="bmap-stats">' +
        '<div><b>' + c.jobs.length + '</b><span>roles queued</span></div>' +
        '<div><b>' + c.posts.length + '</b><span>post' + (c.posts.length === 1 ? '' : 's') + ' waiting</span></div>' +
      '</div>' +
      (c.posts.length ? '<ul class="bmap-posts">' + posts + '</ul>' : '');
  }
  function showPost(c, p, btn) {
    fan.querySelectorAll('.on').forEach(function (e) { e.classList.remove('on'); });
    btn.classList.add('on');
    var jobs = c.jobs.filter(function (j) { return j.part === p.part; }).map(function (j) {
      return '<li><div>' + esc(j.title) + '<span>' + esc(j.company || 'Company not listed') + '</span></div></li>';
    }).join('');
    panel.innerHTML =
      '<div class="kick">' + esc(c.short) + (c.posts.length > 1 ? ' &middot; part ' + p.part : '') + '</div>' +
      '<h3>' + (p.when === 'today' ? 'Posts today' : 'Posts ' + esc(p.when)) + '</h3>' +
      '<p class="sub">' + p.n + ' role' + (p.n === 1 ? '' : 's') + ' in this post</p>' +
      '<img src="' + esc(p.cover) + '" alt="cover" loading="lazy">' +
      '<ul class="bmap-posts">' + jobs + '</ul>';
  }
  function showJob(c, j, btn) {
    fan.querySelectorAll('.on').forEach(function (e) { e.classList.remove('on'); });
    btn.classList.add('on');
    panel.innerHTML =
      '<div class="kick">' + esc(c.short) + ' &middot; ' + (j.when === 'today' ? 'posts today' : 'posts ' + esc(j.when)) + '</div>' +
      '<h3>' + esc(j.title) + '</h3>' +
      '<p class="sub">' + esc(j.company || 'Company not listed') + '</p>' +
      '<img src="' + esc(j.img) + '" alt="the slide" loading="lazy">' +
      '<a class="go" href="' + esc(j.url) + '" target="_blank" rel="noopener">Open on Seek &#8599;</a>';
  }

  function select(i) {
    current = i;
    Array.prototype.forEach.call(catsEl.children, function (el, k) { el.classList.toggle('on', k === i); });
    layoutFan(DATA.cats[i]);
    showCat(DATA.cats[i]);
    requestAnimationFrame(draw);
  }

  select(current);
  window.addEventListener('resize', function () { layoutFan(DATA.cats[current]); draw(); });
})();
</script>
"""


def map_block(queue, now=None):
    """The whole Map section as HTML. Never raises -- a broken map must not
    take the rest of the dashboard down with it."""
    try:
        data = map_data(queue, now)
    except Exception as e:                       # noqa: BLE001
        return f"<!-- map skipped: {type(e).__name__}: {e} -->"
    # "</" inside the JSON would end the <script> early, so escape it.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__MAP_DATA__", blob)
