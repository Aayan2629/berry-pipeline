"""
search_terms.py -- what we ask the job boards for.

These lists used to live in run_all.py, the old Scrapy driver. That driver is
gone (seek.py talks to Seek's API directly and is twenty times faster),
but the terms it accumulated are the useful part: searching only for "intern"
finds a fraction of what is actually out there, which is why this list is 73
terms long rather than one.
"""

def _dedupe(seq):
    """Keep the first occurrence of each term -- several appear in more than
    one group, and searching the same words twice is wasted minutes."""
    seen, out = set(), []
    for t in seq:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out

QUICK_TERMS = [
    "intern",
    "internship",
    "software engineering intern",
    "data science intern",
    "accounting intern",
    "engineering intern",
    "vacation program",
    "cadetship",
]

# ---- everything, grouped by the category each term is aimed at -------------
BROAD_TERMS = [
    "intern", "internship", "summer intern", "winter intern",
    "student intern", "industry placement", "work experience program",
    "summer analyst", "summer program",
]

COMPSCI_TERMS = [
    "software engineering intern", "software intern", "software developer intern",
    "computer science intern", "developer intern", "programming intern",
    "web development intern", "full stack intern", "devops intern",
    "IT intern", "information technology intern", "IT support intern",
    "cyber security intern", "cloud intern", "network intern",
    "technology intern",
]

DATA_TERMS = [
    "data science intern", "data analyst intern", "data intern",
    "data engineering intern", "analytics intern", "business intelligence intern",
    "AI intern", "artificial intelligence intern", "machine learning intern",
    "actuarial intern", "quantitative intern", "statistics intern",
]

FINANCE_TERMS = [
    "finance intern", "accounting intern", "banking intern", "commerce intern",
    "marketing intern", "digital marketing intern", "brand intern",
    "social media intern", "communications intern", "advertising intern",
    "business intern", "economics intern", "investment intern", "audit intern",
    "tax intern", "consulting intern", "insurance intern",
    "business analyst intern", "corporate finance intern", "trading intern",
    "wealth management intern",
]

ENGINEERING_TERMS = [
    "engineering intern", "engineering internship", "student engineer",
    "trainee engineer", "engineering cadet",
    "mechanical engineering intern", "civil engineering intern",
    "electrical engineering intern", "chemical engineering intern",
    "structural engineering intern", "environmental engineering intern",
    "vacation program", "vacation student", "undergraduate program",
    "cadetship",
]


def _dedupe(seq):
    """Keep the first occurrence of each term -- several appear in more than
    one group, and searching the same words twice is wasted minutes."""
    seen, out = set(), []
    for t in seq:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


SEARCH_TERMS = _dedupe(BROAD_TERMS + COMPSCI_TERMS + DATA_TERMS
                       + FINANCE_TERMS + ENGINEERING_TERMS)
