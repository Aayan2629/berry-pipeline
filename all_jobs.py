"""
all_jobs.py -- the shared rulebook. No AI anywhere in here.

This file used to build a page of its own. It no longer does: the website is
build_site.py's job and the carousels are build_carousels.py's. What survived
is the part every other script needs to agree on, so that a listing is sorted
the same way whether it turns up on the site or on a slide.

WHAT THE REST OF THE PIPELINE IMPORTS FROM HERE

    categorize(title, description)      which of the 24 specialties a role is
    is_internship(title, description)   intern/cadet/vacation, not a senior role
    job_track(title, description)       "internship" vs "graduate"
    job_age_days(date_posted)           how old a posting is, in days
    load_dead_listings()                ids Seek has told us are Expired
    MAX_AGE_DAYS                        how old a listing may be before we drop it

Everything is plain keyword and regex rules that you can read and change --
CATEGORY_RULES, INTERNSHIP_TITLE_WORDS, DEADLINE_PATTERNS and friends below.
If a job lands in the wrong category, the fix is a word in one of those lists.

WHO CALLS IT

    SeekSpider-main/pipeline_scripts/build_site.py
    SeekSpider-main/pipeline_scripts/build_carousels.py
    SeekSpider-main/pipeline_scripts/check_live.py
    SeekSpider-main/scrapers/other_boards.py

The scraping itself lives in SeekSpider-main/scrapers/ (seek.py and
other_boards.py) and the one command that runs everything is
SeekSpider-main/pipeline_scripts/refresh.py.
"""

import json
import os
import re
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# ===========================================================================
# SETTINGS -- change these if you want
# ===========================================================================
# The search terms themselves live with the scrapers that use them, in
# SeekSpider-main/scrapers/search_terms.py. What lives here is only the rules
# for judging a listing once one of those searches has already found it.

# Drop anything posted more than this many days ago. Job boards keep stale
# listings up for months (there were listings from April, and one from 2024,
# in the last run) and those are almost always closed by now. Listings with
# no posted date at all are KEPT, since we can't tell how old they are --
# better to show one that might be stale than hide a fresh one.
MAX_AGE_DAYS = 21

# A job must look like an internship to appear at all.
INTERNSHIP_TITLE_WORDS = [
    "intern", "internship", "graduate program", "graduate programme",
    "vacation program", "vacationer", "cadetship", "student program",
    "trainee", "work experience", "placement",
]
# Only these stronger phrases count when found in the DESCRIPTION rather
# than the title -- stops a senior role that merely mentions "our
# internship program" from sneaking in.
INTERNSHIP_DESC_PHRASES = [
    "internship program", "internship programme", "summer internship",
    "intern program", "graduate program", "graduate programme",
    "vacation program", "cadetship",
]

# A job must look like it's in Sydney.
SYDNEY_WORDS = ["sydney", "nsw", "new south wales"]

# ===========================================================================
# CATEGORIES -- same 24 as jobspy_demo/app.py
# ===========================================================================
# The ONLY seven categories that appear on the page. Anything that doesn't
# fit one of these is dropped entirely -- there's deliberately no
# "Other / Uncategorized" section.
#
# ORDER MATTERS: the first category whose keyword matches wins, so the
# most specific ones are listed first (a "Software Engineer Intern" should
# land in Comp Sci, not get grabbed by the broad "engineer" rule further
# down).
# Four categories, in this order. Order matters: the FIRST list whose keyword
# appears in the title wins, so the narrow, specific fields are checked before
# the broad ones. A "Data Engineer" must reach Data Science before Engineering
# claims it; a "Software Engineer" must reach Computer Science first. Anything
# matching none of these is dropped entirely rather than forced somewhere.
CATEGORY_RULES = [
    ("Technology, Data & AI", [
        # Computer science, software, IT, data and actuarial are one category
        # rather than two. They are the same students -- at UNSW computer
        # science sits inside the Faculty of Engineering, at UTS it is the
        # Faculty of Engineering and IT -- and separately each was producing
        # two- and three-slide carousels, which read as an account with
        # nothing to post.
        # data, AI, analytics
        "data scientist", "data analyst", "data engineer", "data science",
        "machine learning", "ml engineer", " ai ", " ai,", "artificial intelligence",
        "business intelligence", "analytics", "data analytics", " bi ",
        "quantitative", "quant ", "algorithm", "deep learning",
        "natural language", "computer vision", "data mining",
        "actuarial", "actuary", "statistics", "statistical", "biostatistics",
        # software and computer science
        "software", "developer", "programmer", "full stack", "fullstack",
        "front end", "frontend", "back end", "backend", "web develop",
        "mobile develop", "app develop", "devops", "computer science",
        "qa engineer", "test engineer", "software engineer", "ios ", "android",
        "game develop", "sde ", "coding", "programming",
        "kernel", "embedded", "api ", "platform engineer", "bootcamp",
        "software academy",
        # IT and infrastructure
        "it support", "help desk", "helpdesk", "systems administrator",
        "network engineer", "cyber security", "cybersecurity",
        "information security", "it technician", "information technology",
        " it ", " ict ", "cloud", "database", "technology",
        "information systems", "digital transformation", "solutions architect",
        "it infrastructure", "cloud infrastructure",
    ]),
    ("Engineering", [
        "mechanical engineer", "civil engineer", "electrical engineer",
        "chemical engineer", "aerospace", "mining engineer", "industrial engineer",
        "structural engineer", "process engineer", "manufacturing engineer",
        "geotechnical", "hydraulic", "fire safety engineer", "quality engineer",
        "environmental engineer", "renewable energy", "mechatronic",
        "biomedical engineer", "materials engineer", "project engineer",
        "site engineer", "engineering intern", "engineering internship",
        "vacation student", "engineer intern", "engineering",
        # Bare "engineer" goes last, and this whole list sits after Data Science
        # and Computer Science, so their engineers are already claimed.
        #
        # NOTE: "cadetship", "vacation program" and "undergraduate program" are
        # deliberately NOT here. They are search terms -- how you find these
        # ads on Seek -- not evidence a role is engineering. Having them here
        # filed a Legal Cadetship, a Journalism Cadetship, a Teacher Cadetship
        # and a nightclub Security Cadetship all under Engineering.
        "engineer", "surveying", "drafting", "cad ", "trainee engineer",
        "r&d", "research and development", "product design",
        "engineering cadet", "engineering vacation",
    ]),
    ("Business, Commerce, Marketing & Finance", [
        "finance", "financial", "accounting", "accountant", "audit", " tax ",
        "bookkeep", "banking", "investment", "treasury", "fp&a",
        "commerce", "economics", "economist", "insurance", "superannuation",
        "advisory", "wealth", "asset management", "private equity", "venture",
        "trading", "trader", "equities", "business analyst", "consulting",
        "consultant", "strategy", "sales", "business development",
        "account manager", "account executive", "supply chain", "logistics",
        "procurement", "operations", "management trainee", "commercial",
        # Marketing lives here rather than in its own category: on Seek it is
        # advertised alongside sales, brand and communications work by the
        # same commercial teams, and splitting it left both sides thin.
        "marketing", "digital marketing", "brand", "social media",
        "content intern", "communications", "public relations",
        "advertising", "market research", "seo", "ecommerce", "e-commerce",
        "customer experience", "growth",
    ]),
]

# When a title matches nothing, fall back to scanning the description -- but
# ONLY with these longer, unambiguous phrases. Reusing every keyword above put
# a fire-safety engineering role in IT because its description said
# "infrastructure". Single vague words do too much damage here.
DESCRIPTION_FALLBACK_RULES = [
    ("Technology, Data & AI", [
        "data science", "machine learning", "data analytics",
        "artificial intelligence", "actuarial studies", "actuarial degree",
        "software engineering", "software development", "software developer",
        "computer science degree", "full stack develop", "web development",
        "cyber security", "information technology degree",
    ]),
    ("Engineering", [
        "engineering degree", "engineering student", "engineering discipline",
        "studying engineering",
    ]),
    ("Business, Commerce, Marketing & Finance", [
        "accounting degree", "finance degree", "commerce degree",
        "financial services", "chartered accountant", "studying commerce",
        "investment banking", "financial institution", "wealth management",
        "studying accounting", "studying finance", "marketing degree",
        "studying marketing", "marketing team",
    ]),
]

DEADLINE_PATTERNS = [
    r"applications?\s+clos\w*[^.\n]{0,15}?(\d{1,2}[\/\-\s][A-Za-z0-9]+[\/\-\s]\d{2,4})",
    r"closing\s+date[^.\n]{0,15}?(\d{1,2}[\/\-\s][A-Za-z0-9]+[\/\-\s]\d{2,4})",
    r"apply\s+by[^.\n]{0,15}?(\d{1,2}[\/\-\s][A-Za-z0-9]+[\/\-\s]\d{2,4})",
    r"deadline[^.\n]{0,15}?(\d{1,2}[\/\-\s][A-Za-z0-9]+[\/\-\s]\d{2,4})",
]
NOT_LISTED = "Not listed on posting"


# ===========================================================================
# Shared helpers
# ===========================================================================
def categorize(title, description):
    """
    Decide which of the seven categories a job belongs to, or None if it
    doesn't belong in any of them (those jobs are dropped from the page).

    The job TITLE is checked first and is trusted completely -- it's by far
    the most reliable signal. Only if the title matches nothing do we look
    at the description, and then only for unambiguous multi-word phrases.
    """
    padded_title = f" {(title or '').lower()} "
    for category, keywords in CATEGORY_RULES:
        if any(k in padded_title for k in keywords):
            return category

    desc = (description or "").lower()
    for category, phrases in DESCRIPTION_FALLBACK_RULES:
        if any(p in desc for p in phrases):
            return category

    return None


def find_deadline(description):
    if not description:
        return NOT_LISTED
    for pattern in DEADLINE_PATTERNS:
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            return m.group(1)
    return NOT_LISTED


# Whole-word patterns. Plain substring matching was quietly wrong: the word
# "intern" appears inside "INTERnational", so ING's "International Talent
# Programme" was being counted as an internship on the strength of a word
# that wasn't there. \b markers stop that while still catching the real
# plurals ("intern", "interns", "internship", "internships").
_INTERN_RE = re.compile(
    r"\b(intern|interns|internship|internships|vacationer|cadetship"
    r"|trainee|traineeship|vacation program(me)?|student program(me)?"
    r"|work experience|industry placement|summer program(me)?)\b", re.I)

# Words that mean the ad is for someone SENIOR who works with graduates
# (a "Graduate Recruitment Manager"), not a graduate role itself.
_SENIORITY_RE = re.compile(
    r"\b(senior|manager|head|director|lead|principal|chief|partner"
    r"|recruiter|recruitment)\b", re.I)

_GRAD_RE = re.compile(
    r"\b(graduate|graduates|grad)\b", re.I)

_GRAD_STRONG_RE = re.compile(
    r"\b(graduate|grad)\s+(program(me)?|role|position|opportunit(y|ies)"
    r"|scheme|intake|experience|engineer|analyst|consultant|developer|pharmacist)"
    r"|\bgraduate\s+\w+\s+program(me)?\b", re.I)


def is_internship(title, description, extra=""):
    """True for internships AND graduate programs -- both belong on the page.
    job_track() below decides which of the two sections it goes in."""
    head = f"{title or ''} {extra or ''}"
    if _INTERN_RE.search(head):
        return True
    # A bare "Graduate" anywhere in the title counts -- it turns up at the
    # end as often as the start ("...Engineer Graduate - 2027 Start") -- but
    # not when the title also reads as a senior role, which is how a
    # "Graduate Recruitment Manager" would otherwise sneak onto the page.
    if _GRAD_RE.search(head) and not _SENIORITY_RE.search(head):
        return True
    desc = (description or "").lower()
    if any(p in desc for p in INTERNSHIP_DESC_PHRASES):
        return True
    return bool(_GRAD_STRONG_RE.search(description or ""))


def job_track(title, description, extra=""):
    """
    Split into the page's two top sections: 'Internships' or
    'Graduate Programs'.

    The title decides it wherever possible. An explicit "intern" beats
    everything, since plenty of grad-program ads mention graduates in
    passing. Only when the title says nothing either way do we read the
    description -- which is how ING's "International Talent Programme"
    lands correctly in Graduate Programs, its ad calling it "an 18-month
    graduate experience ... for ambitious technology graduates".
    """
    head = f"{title or ''} {extra or ''}"
    if _INTERN_RE.search(head):
        return "Internships"
    if _GRAD_RE.search(head):
        return "Graduate Programs"

    desc = description or ""
    if _GRAD_STRONG_RE.search(desc):
        return "Graduate Programs"
    if _INTERN_RE.search(desc):
        return "Internships"
    # Nothing conclusive -- default to Internships, the account's focus.
    return "Internships"


def is_sydney(location):
    loc = (location or "").lower()
    return any(w in loc for w in SYDNEY_WORDS)


# Words that differ between boards for the SAME employer and mean nothing
# for identity: LinkedIn says "ING Australia", Seek says "ING"; Indeed says
# "Zurich Insurance", LinkedIn says "Zurich Australia".
_COMPANY_NOISE = {
    "pty", "ltd", "limited", "inc", "incorporated", "plc", "llc", "group",
    "holdings", "australia", "australian", "au", "nz", "corporation", "corp",
    "co", "the", "company", "and", "&",
}


def normalise_title(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def company_key(company):
    """
    Reduce a company name to its identifying word(s), so the same employer
    matches across boards. 'ING Australia' and 'ING' both become 'ing';
    'Zurich Insurance' and 'Zurich Australia' both become 'zurich'.

    Only the first meaningful word is used, which is deliberately loose --
    it's safe here because a duplicate ALSO has to have a character-for-
    character identical job title before anything gets merged.
    """
    words = re.sub(r"[^a-z0-9 ]+", " ", (company or "").lower()).split()
    words = [w for w in words if w not in _COMPANY_NOISE]
    return words[0] if words else ""


def job_age_days(date_posted):
    """Days since posting, or None when the board didn't give a date."""
    if not date_posted:
        return None
    text = str(date_posted).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            posted = datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
            return (datetime.now() - posted).days
        except ValueError:
            continue
    try:
        posted = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        return (datetime.now() - posted).days
    except (ValueError, AttributeError):
        return None


def info_score(job):
    """How complete a record is -- used to decide which copy of a duplicate
    to keep, so we don't throw away the one with the salary and description."""
    return sum(1 for f in ("description", "pay", "job_type", "location",
                           "date_posted", "company") if job.get(f))


def esc(value):
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def pretty_date(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y")
    except (ValueError, AttributeError):
        return str(value)[:10]


# ===========================================================================
# SOURCE 1 -- Seek (from SeekSpider crawls already on disk)
# ===========================================================================

# ---------------------------------------------------------------------------
# Listings that have closed since we scraped them
# ---------------------------------------------------------------------------
# check_live.py asks Seek about each job by id and records whether it is still
# Active. We deliberately do NOT infer this from a job's absence in the latest
# crawl: the crawl is capped, so a live job can be missing simply because it
# fell past the limit, and deleting on that basis would remove open roles.
# A job with no recorded status is kept -- this file can only remove listings
# Seek has positively told us are dead.
LISTING_STATUS_FILE = os.path.join(
    HERE, "SeekSpider-main", "pipeline_scripts", "listing_status.json")


def load_dead_listings():
    """Job ids Seek reports as Expired or deleted."""
    try:
        with open(LISTING_STATUS_FILE, encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, ValueError):
        return set()
    return {str(jid) for jid, info in recorded.items()
            if (info or {}).get("status") not in (None, "Active")}
