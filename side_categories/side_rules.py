"""
side_categories/side_rules.py -- the rulebook for the two NEW categories.

    Architecture       (planned posting day: Wednesday)
    Medicine & Health  (planned posting day: Sunday)

This is the side version of all_jobs.py. It deliberately lives in its own
folder and nothing in the main pipeline imports it, so Tech, Business and
Engineering can't be affected by anything in here. When both categories are
working we'll copy these lists into all_jobs.py / search_terms.py properly.

No AI anywhere in here -- same as the main rulebook, it's all plain keyword
lists you can read and edit. If a job lands in the wrong place, the fix is a
word in one of the lists below.

C comparison: think of this file as a header (.h) full of constant arrays
plus a couple of small helper functions. Python lists [ ... ] are like C
arrays of strings, except they can grow and you don't manage the memory.
"""

import re

# ===========================================================================
# 1. SEARCH TERMS -- what we type into Seek's search box
# ===========================================================================
# Each term is one search. More terms = more jobs found, but each one costs
# a few seconds. These are kept SEPARATE per category on purpose: you said
# Architecture and Medicine are two different things, never combined.

ARCHITECTURE_TERMS = [
    "architecture intern", "architectural intern", "architecture internship",
    "architecture student", "architectural student", "student architect",
    "architectural assistant", "architecture cadet",
    "interior architecture intern", "interior design intern",
    "landscape architecture intern", "urban design intern",
    "urban planning intern", "town planning intern", "planning cadet",
    "architectural drafting intern", "architecture vacation",
]

# Medicine is tricky: in Australia a "medical intern" is usually a
# first-year DOCTOR (after graduating), and most student roles aren't called
# internships at all. So we also search for summer research scholarships,
# student lab roles, pharmacy interns, etc. The test run tells us which of
# these actually find anything -- the useless ones can be deleted later.
MEDICINE_TERMS = [
    "medical intern", "medicine intern", "medical internship",
    "medical student", "health intern", "healthcare intern",
    "clinical intern", "hospital intern", "pharmacy intern",
    "intern pharmacist", "pharmacy student", "nursing student",
    "undergraduate nurse", "physiotherapy student", "psychology intern",
    "research intern", "medical research intern", "summer research scholarship",
    "laboratory intern", "lab intern", "science intern", "biomedical intern",
    "biotech intern", "pharmaceutical intern", "public health intern",
    "dental student", "allied health student",
]

# LAW (added Oct 2026). Law students almost never get called "interns".
# The real names, roughly in order of how common they are on Seek:
#   * clerkships -- summer / winter / seasonal / vacation clerkships at law
#     firms (the big one; NSW firms run summer AND winter rounds)
#   * law clerk / summer clerk / winter clerk
#   * paralegal and legal assistant roles aimed at law students
#   * legal intern / legal internship (in-house teams, govt, startups)
#   * legal cadet / law cadetship (some councils and government agencies)
#   * PLT = Practical Legal Training placement (final step before admission)
#   * community legal centre volunteer / student roles
LAW_TERMS = [
    "clerkship", "law clerkship", "summer clerkship", "winter clerkship",
    "seasonal clerkship", "vacation clerkship", "summer clerk", "winter clerk",
    "seasonal clerk", "law clerk", "legal clerk",
    "law student", "law students", "student paralegal", "paralegal law student",
    "paralegal student", "legal assistant law student",
    "legal intern", "legal internship", "law intern", "law internship",
    "in-house legal intern", "legal cadet", "legal cadetship", "law cadet",
    "practical legal training", "PLT placement", "legal volunteer",
    "community legal centre student", "legal research assistant",
    "law graduate clerk",
]

# The dictionary below maps "category name" -> its search terms.
# (A Python dict is like a lookup table / R named list: SIDE_TERMS["Architecture"]
# gives you the list of Architecture terms.)
SIDE_TERMS = {
    "Architecture": ARCHITECTURE_TERMS,
    "Medicine & Health": MEDICINE_TERMS,
    "Law": LAW_TERMS,
}

# ===========================================================================
# 2. CATEGORY KEYWORDS -- how we decide a job IS architecture / medicine
# ===========================================================================
# Checked against the job TITLE (lowercased, with a space added at each end
# so " lab " can match a whole word).

ARCHITECTURE_KEYWORDS = [
    "architect", "architectural", "architecture",
    "interior design", "landscape architect", "urban design",
    "urban planning", "town planning", "town planner", "urban planner",
    "strategic planning",
]

# Titles that SAY "architect" but are really tech jobs. The main pipeline
# already files these under "Technology, Data & AI", so we must skip them
# or a "Solutions Architect Intern" would show up in two places.
ARCHITECTURE_EXCLUDE = [
    "solutions architect", "solution architect", "software architect",
    "cloud architect", "data architect", "enterprise architect",
    "security architect", "technical architect", "it architect",
    "systems architect", "network architect", "salesforce architect",
    "infrastructure architect", "integration architect",
]

MEDICINE_KEYWORDS = [
    "medical", "medicine", "clinical", "clinic", "hospital", "health",
    "healthcare", "patient", "pharmacy", "pharmacist", "pharmaceutical",
    "nurse", "nursing", "physio", "physiotherap", "psycholog",
    "dental", "dentist", "optometr", "radiograph", "radiolog", "sonograph",
    "pathology", "laborator", " lab ", "biomedical science",
    "biomedical research", "medical research", "occupational therap",
    "speech patholog", "dietitian", "nutrition", "paramedic",
    "epidemiolog", "public health", "neuroscience", "biotech",
    "life science", "genomic", "immunolog", "vaccine", "doctor",
    "allied health", "aged care", "disability support",
]

# "Health" is a broad word. These are jobs that contain it but aren't
# medicine at all.
MEDICINE_EXCLUDE = [
    "health and safety", "health & safety", "whs", "ohs", "hse ",
    "health insurance", "financial health",
    "biomedical engineer",   # the main pipeline files this under Engineering
]

# LAW: is this job IN law? Regex with \b (word boundary) so "law" doesn't
# match "lawn mowing" or "Lawson St", and "jd" doesn't match "jdk".
_LAW_TITLE_RE = re.compile(
    r"\b(law|laws|legal|paralegal|paralegals|clerkship|clerkships|solicitor"
    r"|solicitors|lawyer|lawyers|litigation|barrister|barristers|juris doctor"
    r"|jd|llb|plt|practical legal training)\b", re.I)

# Has a law word, but isn't a law job.
LAW_EXCLUDE = [
    "law enforcement", "legal secretary", "medico-legal typist",
    "security", "lawn",
]

# Longer, unambiguous phrases we're allowed to look for in the DESCRIPTION
# when the title gives nothing away (e.g. "2027 Summer Vacation Program").
# Same idea as DESCRIPTION_FALLBACK_RULES in all_jobs.py.
ARCHITECTURE_DESC_PHRASES = [
    "architecture degree", "studying architecture", "architecture student",
    "bachelor of architecture", "master of architecture",
    "architectural practice", "architecture practice", "architecture firm",
    "interior design degree", "landscape architecture",
]
LAW_DESC_PHRASES = [
    "law student", "law students", "studying law", "bachelor of laws",
    "juris doctor", "clerkship program", "seasonal clerkship",
    "summer clerkship", "winter clerkship", "practical legal training",
    "penultimate year law", "penultimate-year law", "final year law",
]
MEDICINE_DESC_PHRASES = [
    "medical degree", "studying medicine", "medical student",
    "doctor of medicine", "bachelor of medicine", "nursing degree",
    "studying nursing", "pharmacy degree", "studying pharmacy",
    "health sciences", "biomedical science", "medical research institute",
    "clinical research", "clinical trials", "research scholarship",
]

# ===========================================================================
# 3. "IS THIS A STUDENT ROLE?" -- extra words for these two fields
# ===========================================================================
# The main pipeline only keeps titles with "intern", "cadetship", "vacation
# program" etc. Architecture and medicine jobs for students are often called
# something else ("Architecture Student", "Summer Research Scholarship"), so
# the side version ALSO accepts these words in the title.
#
# \b means "word boundary" -- so "student" matches "Student" but not
# "studentship..." partially. (Same regex idea as grepl() in R.)
_SIDE_STUDENT_RE = re.compile(
    r"\b(student|students|undergraduate|undergrad|cadet|scholarship"
    r"|scholarships|vacation|summer research|work integrated learning)\b",
    re.I)


def is_student_role(title):
    """True when the TITLE has one of the extra student words above.

    The scraper uses this on top of the main is_internship() check,
    not instead of it."""
    return bool(_SIDE_STUDENT_RE.search(title or ""))


# ===========================================================================
# 3b. ARCHITECTURE: graduate roles ARE allowed (your decision)
# ===========================================================================
# Architecture firms in Sydney basically never say "intern" -- the entry
# level job is "Architectural Graduate" / "Graduate of Architecture". So for
# Architecture ONLY, graduate roles are kept. (Main categories still drop
# grad programs; this doesn't change them.)
#
# But some ads say "graduate" while really wanting someone experienced
# ("Experienced Graduate or Architect", "Graduate to Intermediate Level",
# "Project Architect / Graduate"). Any of these words kills it:
_ARCH_GRAD_NOT_ENTRY_RE = re.compile(
    r"\b(experienced|senior|intermediate|mid|associate|lead|leader"
    r"|project architect)\b|graduate to", re.I)


def is_entry_level_architecture_grad(title):
    """True for a real entry-level architecture graduate role.

    Examples:
      "Architectural Graduate"                      -> True
      "Graduate of Architecture"                    -> True
      "Experienced Graduate or Architect ..."       -> False
      "Town Planner - Graduate to Intermediate"     -> False
    """
    t = title or ""
    return bool(re.search(r"\bgrad(uate)?s?\b", t, re.I)) and \
        not _ARCH_GRAD_NOT_ENTRY_RE.search(t)


# ===========================================================================
# 3c. MEDICINE: clear student roles only
# ===========================================================================
# Some pharmacy ads are really a normal job with "intern" tacked on, e.g.
# "Dispensary Technician / Intern Pharmacist" or "Pharmacy Assistant".
# Those get dropped. A title with one of these words is out...
MEDICINE_NOT_STUDENT_WORDS = [
    "technician", "dispensary", "pharmacy assistant", "wardsperson",
    "trainee",
]
# ...UNLESS it also clearly says it's for a student, like
# "Assistant in Nursing - Student Nurse".
_MED_CLEARLY_STUDENT_RE = re.compile(
    r"\b(student|students|undergraduate|undergrad)\b", re.I)


def is_clear_medicine_student_role(title):
    """False for mixed 'real job + intern' ads, True otherwise."""
    t = (title or "").lower()
    if _MED_CLEARLY_STUDENT_RE.search(t):
        return True
    return not any(w in t for w in MEDICINE_NOT_STUDENT_WORDS)


# ===========================================================================
# 3d. LAW: clear student roles only (same idea as Medicine)
# ===========================================================================
# A plain "Paralegal" or "Legal Assistant" is a normal job that wants
# experience. It only counts when the TITLE also says it's for students.
# Clerkships, clerks, interns, cadets and PLT placements always count.
# "Clerk" on its own is NOT here: "Litigation Support Clerk" and
# "Accounts/Admin Clerk" are ordinary admin jobs. Only the law-student
# clerk names count. "Trainee"/"traineeship" are left out too -- on Seek
# a "Legal Traineeship" is a school-leaver Cert III, not a law student role.
_LAW_STUDENT_RE = re.compile(
    r"\b(law clerk|law clerks|legal clerk|summer clerk|winter clerk"
    r"|seasonal clerk|vacation clerk|articled clerk|clerkship|clerkships"
    r"|intern|interns|internship|internships|student|students|undergraduate"
    r"|undergrad|cadet|cadetship|vacation|vacationer|work experience"
    r"|volunteer|plt|practical legal training"
    r"|pathway program|pathway programme)\b", re.I)

# "clerk" alone isn't enough when it's an ordinary admin clerk at a firm.
_LAW_NOT_STUDENT_RE = re.compile(
    r"\b(conveyancing clerk|accounts clerk|filing clerk|probate clerk"
    r"|records clerk|senior|experienced|associate|lawyer|solicitor"
    r"|\d\+?\s*(years|yrs)|pqe)\b", re.I)


def is_law_title(title):
    """True when the TITLE says the job is in law."""
    t = (title or "").lower()
    return bool(_LAW_TITLE_RE.search(t)) and not any(x in t for x in LAW_EXCLUDE)


def has_law_student_word(title):
    """The student half of the check on its own, for titles like "Seasonal
    Clerk - Corporate" that don't say law -- the description decides those."""
    t = title or ""
    if _LAW_NOT_STUDENT_RE.search(t) and not re.search(
            r"\b(student|students|clerkship|clerkships)\b", t, re.I):
        return False
    return bool(_LAW_STUDENT_RE.search(t))


def says_law_student_in_teaser(title, teaser):
    """A plain "Paralegal - Casual" whose ad summary says it wants a LAW
    STUDENT ("Ambitious law student with outstanding academics...")."""
    t = title or ""
    return is_law_title(t) and not _LAW_NOT_STUDENT_RE.search(t) and \
        not re.search(r"\b(senior|graduate|lawyer|solicitor|counsel)\b", t, re.I) \
        and bool(re.search(r"\blaw students?\b", teaser or "", re.I))


def is_law_student_role(title):
    """True for clerkships / law clerks / legal interns / student paralegals.

    Examples:
      "Summer Clerkship Program 2026/27"         -> True
      "Paralegal - Law Student (Part Time)"      -> True
      "Law Clerk"                                -> True
      "Paralegal"                                -> False (normal job)
      "Senior Associate - Litigation"            -> False
      "Lawyer / Solicitor 2+ years PQE"          -> False
    """
    return is_law_title(title) and has_law_student_word(title)


# ===========================================================================
# 4. categorize_side() -- the decision function
# ===========================================================================
def categorize_side(title, description=""):
    """
    Returns "Architecture", "Law", "Medicine & Health", or None.

    Order of checks (like a chain of if / else if in C):
      1. title matches an Architecture keyword and NOT a tech-architect
         title                                    -> "Architecture"
      2. title matches a Medicine keyword and NOT an exclude
                                                  -> "Medicine & Health"
      3. title says nothing -> try the description phrases, same order
      4. otherwise                                -> None (not ours)
    """
    t = f" {(title or '').lower()} "

    if any(k in t for k in ARCHITECTURE_KEYWORDS) and \
       not any(x in t for x in ARCHITECTURE_EXCLUDE):
        return "Architecture"

    # Law sits before Medicine so a "Medico-Legal Intern" or "Health Law
    # Clerk" is filed as Law (it's a law job that happens to be about health).
    if is_law_title(t):
        return "Law"

    if any(k in t for k in MEDICINE_KEYWORDS) and \
       not any(x in t for x in MEDICINE_EXCLUDE):
        return "Medicine & Health"

    d = (description or "").lower()
    if any(p in d for p in ARCHITECTURE_DESC_PHRASES):
        return "Architecture"
    if any(p in d for p in MEDICINE_DESC_PHRASES):
        return "Medicine & Health"
    if any(p in d for p in LAW_DESC_PHRASES):
        return "Law"

    return None
