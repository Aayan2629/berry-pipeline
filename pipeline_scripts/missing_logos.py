#!/usr/bin/env python3
"""
missing_logos.py -- which employers still have no logo, most common first.

    python3 missing_logos.py

Roughly half of Seek's listings carry a logo; LinkedIn fills in most of the
rest. What is left gets an initials tile, which is fine for a one-off small
business and not fine for a name people recognise.

Fixing one is a single line in brand_domains.json. This tells you which lines
are worth adding: a company appearing eight times is worth thirty seconds, a
company appearing once is not.

We do not look domains up automatically. Every logo service needs a domain,
and turning a company NAME into a domain is the part that gets things wrong --
"Holden Bolster Avenir Pty Ltd" could be anything, and a wrong logo on a job
post is worse than no logo. Check the domain yourself, add the line, done.
"""

import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))   # repo root, for GitHub Actions
sys.path.insert(0, HERE)

from build_carousels import load_all_jobs, real_company          # noqa: E402
from poster_template import brand_domain                          # noqa: E402


def main():
    counts, has_logo = collections.Counter(), set()
    for j in load_all_jobs():
        name = real_company(j.get("company_name") or j.get("business_name"))
        if not name:
            continue
        counts[name] += 1
        if j.get("logo_url"):
            has_logo.add(name)

    missing = [(n, c) for n, c in counts.most_common()
               if n not in has_logo and not brand_domain(n)]

    covered = len(counts) - len(missing)
    print(f"{covered} of {len(counts)} employers have a logo "
          f"({100 * covered // max(len(counts), 1)}%)\n")

    if not missing:
        print("Every employer seen so far has one. Nothing to do.")
        return 0

    print("No logo yet, most frequent first:\n")
    for name, n in missing[:25]:
        star = " <-- worth adding" if n >= 3 else ""
        print(f"  {n:>2}x  {name}{star}")

    print(f"\n  ...{len(missing)} employers in total\n")
    print("To fix one: check the company's real website, then add a line to")
    print("brand_domains.json:\n")
    print(f'      "{missing[0][0]}": "example.com.au",\n')
    print("Rebuild and it appears on every future slide and on the site.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
