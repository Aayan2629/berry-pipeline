# Running berry on GitHub, hands off

Free. GitHub Actions costs nothing on a private repo up to 2,000 minutes a
month, and this uses roughly 250.

Do these in order. Step 1 decides whether the rest is worth doing.

---

## 1. Find out if the job boards will talk to GitHub

**This is the one that can sink the whole plan, so it goes first.**

Your scrapers work from your flat because they come from a normal home
internet connection. GitHub's runners are in Microsoft Azure datacentres, and
Seek, LinkedIn, Indeed and Glassdoor treat datacentre addresses very
differently. They might answer normally. They might hand back nothing at all.

Nobody can tell you which from a desk. Ten minutes finds out.

1. Make a **private** repo called `berry-pipeline`.
2. Push `SeekSpider-main` to it (commands at the bottom).
3. Actions tab → **0. Can the scrapers run here?** → Run workflow.
4. Read the job counts at the end.

**Dozens or hundreds of jobs:** good, carry on to step 2.

**Zeroes, 403s, or empty files:** stop. The boards are blocking the
datacentre and no amount of workflow YAML fixes that. Come back and we will
schedule it on your Mac instead, which is also free and uses the connection
that already works.

---

## 2. Put your keys in as secrets

Settings → Secrets and variables → Actions → New repository secret.

Copy each value straight out of your `.env`:

| Secret | Where it comes from |
|---|---|
| `IG_USER_ID` | `.env` |
| `IG_ACCESS_TOKEN` | `.env` |
| `IG_TOKEN_OBTAINED` | `.env`, the date, e.g. `2026-09-02` |
| `NETLIFY_TOKEN` | `.env` |
| `GH_SLIDES_TOKEN` | a token that can push to `berry-slides` |
| `GH_PAT` | a token that can write secrets on this repo |

The last two are new. Both from github.com → Settings → Developer settings →
Personal access tokens → Fine-grained tokens:

- **`GH_SLIDES_TOKEN`** — repository access: `berry-slides`. Permissions →
  Contents: Read and write. This is how the slides get onto the public web so
  Meta can fetch them.
- **`GH_PAT`** — repository access: `berry-pipeline`. Permissions →
  Secrets: Read and write. This one exists only so the token refresher can
  store a new Instagram token. A workflow cannot change its own secrets with
  the token GitHub hands it, which is a good rule.

**Never commit `.env`.** The workflow writes a fresh one at the start of
every run from these secrets and deletes it at the end, and the runner itself
is destroyed either way. Your scripts did not have to change at all.

---

## 3. Turn it on

Actions tab → **1. berry, daily** → Run workflow. Watch it once, all the way
through.

After that it runs itself at **21:20 UTC**, which is 8:20am Sydney in summer
and 7:20am in winter. GitHub queues scheduled jobs and the top of the hour is
its busiest minute, so this sits at twenty past. There is still no guarantee
on the exact minute. If a post has to land at a precise time, GitHub cron is
the wrong tool.

It runs every day even though you post three times a week. That is on
purpose: `publish_to_instagram.py` already knows the schedule, and on a
non-posting day it finds nothing due and exits happily. Encoding the calendar
in two places is how the two end up disagreeing.

---

## 4. The token, which is the thing that will actually kill this

An Instagram long-lived token lasts sixty days and nothing renews it. Yours
runs out on **1 November 2026**. A system that runs itself perfectly and then
goes silent in November is worse than one you have to poke, because you will
not notice.

**2. Keep the Instagram token alive** runs every Monday and usually does
nothing. When fewer than 25 days are left it asks Meta for a fresh sixty and
writes the new value straight into your secrets, never into a log. Weekly
rather than monthly so one missed run cannot cost you the window.

Run it by hand once now to check `GH_PAT` works.

---

## What you are trading away

You asked for it to post without you seeing it first, so this is the honest
list rather than a warning.

- **Nothing checks the slides.** A duplicate listing, a wrong logo or a
  truncated title goes out publicly with nobody having looked. On an account
  whose pitch is being reliable, that is the real cost.
- **The logo queue stops moving.** Sixty employers are waiting for a yes or
  no from you. Automation does not answer them, so those stay as initials
  tiles until you sit down with the dashboard.
- **Failures arrive by email.** GitHub emails you when a workflow fails. If
  you filter those away you have built something that breaks in silence.

Worth doing later: have the workflow post its slides to yourself somewhere
first and only publish on a thumbs up. That keeps the hands-off part and puts
the one human check back where it earns its keep.

---

## Pushing the repo up the first time

```
cd ~/Desktop/"job account "/SeekSpider-main
git init
git add -A
git commit -m "berry pipeline"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/berry-pipeline.git
git push -u origin main
```

Check `.gitignore` has `.env` in it before that first push. It does, but look
anyway: a token in a git history is out for good, even after you delete the
file, and even in a private repo.
