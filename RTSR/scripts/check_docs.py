#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_docs.py - verify that docs/ stays consistent with the data.

Checks
  1. every run in results/p6/summary2.csv appears in docs/03 with the same satisfied_pct
  2. the deviation count claimed in docs/02 matches the table rows
  3. relative markdown links in docs/ and README.md resolve

Usage:  python3 RTSR/scripts/check_docs.py
Exit code 0 = all good, 1 = problems found.
"""
import csv
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../RTSR
DOCS = os.path.join(REPO, "docs")
SUMMARY = os.path.join(REPO, "results", "p6", "summary2.csv")

problems = []


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def check_summary_in_doc03():
    if not os.path.isfile(SUMMARY):
        problems.append("summary2.csv missing: %s" % SUMMARY)
        return
    doc = read(os.path.join(DOCS, "03_结果与对照.md"))
    with open(SUMMARY, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        run = r["run"].strip()
        pct = r["satisfied_pct"].strip()
        # the doc quotes the satisfied percentage; require the exact string to appear
        if pct not in doc:
            problems.append("docs/03 does not contain %s%% (run %s from summary2.csv)" % (pct, run))
    print("checked %d runs from summary2.csv against docs/03" % len(rows))


def check_deviation_count():
    doc = read(os.path.join(DOCS, "02_实现与偏差.md"))
    m = re.search(r"偏差总表（\*\*唯一清单，共 (\d+) 条\*\*）", doc)
    if not m:
        problems.append("docs/02: cannot find the deviation-count header")
        return
    claimed = int(m.group(1))
    # count table rows inside the deviation section
    start = doc.index("## 4. 偏差总表")
    end = doc.index("### 关于 #11")
    rows = [ln for ln in doc[start:end].splitlines() if ln.startswith("| ") and not ln.startswith("|---")]
    actual = len(rows) - 1  # minus the header row
    if actual != claimed:
        problems.append("docs/02: header claims %d deviations, table has %d" % (claimed, actual))
    else:
        print("deviation count consistent: %d" % actual)


def check_links():
    files = [os.path.join(DOCS, f) for f in sorted(os.listdir(DOCS)) if f.endswith(".md")]
    files.append(os.path.join(REPO, "README.md"))
    # the repository root README links into RTSR/, so it must be validated too
    root_readme = os.path.join(os.path.dirname(REPO), "README.md")
    if os.path.isfile(root_readme):
        files.append(root_readme)
    checked = 0
    for path in files:
        base = os.path.dirname(path)
        for target in re.findall(r"\]\(([^)#]+)\)", read(path)):
            if target.startswith("http") or target.startswith("mailto"):
                continue
            resolved = os.path.normpath(os.path.join(base, target))
            checked += 1
            if not os.path.exists(resolved):
                problems.append("%s: broken link -> %s" % (os.path.relpath(path, REPO), target))
    print("checked %d relative links in %d files" % (checked, len(files)))


def main():
    check_summary_in_doc03()
    check_deviation_count()
    check_links()
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
