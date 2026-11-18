#!/usr/bin/env python3
"""Deterministic summaries of a task's process artifacts for ``/devflow status``.

The status command could describe a task in prose and let the model count
whatever it reads. That answer varies run to run and cannot be pinned by a
``cmd`` acceptance criterion. Anything the status line claims as a number is
parsed here instead, so the same report always yields the same summary.

One rule dominates this module: **"could not parse" is not "found nothing"**.
A section is counted only when a finding was actually recognised in it, and an
explicitly empty section (``（无）``) is distinguished from one full of entries
the parser could not read. Otherwise ``0 high / 0 medium / 0 low`` would read
as "the review passed" when the truth is "nobody could tell".
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

# Severity headings the reviewer template writes (``## high`` …). Matched
# case-insensitively and tolerantly of surrounding text so a heading like
# ``## high（必须修）`` still counts.
_SEVERITY_HEADING = re.compile(r"^#{2,3}\s*(high|medium|low)\b", re.IGNORECASE)

# A finding is a bold list item: ``- **…** — `file:line` ``. Prose bullets
# under the same heading are explanation and are deliberately not counted.
_FINDING = re.compile(r"^\s*[-*]\s+\*\*.+\*\*")

# Anything that looks like an attempted list entry. Used to tell "the section
# is empty" apart from "the section has entries in a shape we cannot read" —
# the second is a parser gap and must not be reported as zero findings.
_LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")


@dataclass(frozen=True)
class ReviewSummary:
    """Counts from a review report.

    ``found`` — the path exists.
    ``readable`` — the file could actually be opened.
    ``parsed`` — at least one finding was recognised, so the counts are
    trustworthy. A report can be found and readable yet not parsed; that
    distinction is the whole point.
    """

    found: bool = False
    readable: bool = False
    parsed: bool = False
    high: int = 0
    medium: int = 0
    low: int = 0

    @property
    def total(self) -> int:
        return self.high + self.medium + self.low


def _scan(content: str) -> ReviewSummary:
    counts = {"high": 0, "medium": 0, "low": 0}
    unreadable_sections: set[str] = set()
    current: str | None = None

    for line in content.splitlines():
        heading = _SEVERITY_HEADING.match(line)
        if heading:
            current = heading.group(1).lower()
            continue
        if line.lstrip().startswith("#"):
            # Any other heading ends the severity section.
            current = None
            continue
        if current is None:
            continue
        if _FINDING.match(line):
            counts[current] += 1
        elif _LIST_ITEM.match(line):
            # An attempted entry in an unrecognised shape.
            unreadable_sections.add(current)

    total = sum(counts.values())
    # Parsed means: we read at least one finding, OR no section contained
    # entries we failed to understand. Either way the numbers are not hiding
    # rows we skipped.
    parsed = total > 0 or _has_empty_sections(content, unreadable_sections)
    return ReviewSummary(
        found=True,
        readable=True,
        parsed=parsed,
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
    )


def _has_empty_sections(content: str, unreadable: set[str]) -> bool:
    """True when every severity section is genuinely empty.

    Reached only when no finding was recognised; *unreadable* holds sections
    that contained list items in a shape we could not parse. If any such
    section exists the report is not "empty", it is "unreadable", so this
    returns False.
    """
    if unreadable:
        return False
    return any(_SEVERITY_HEADING.match(line) for line in content.splitlines())


def parse_review_report(path: Path) -> ReviewSummary:
    """Parse a review report into per-severity counts.

    Fail-safe: an absent file returns ``found=False`` and an unreadable one
    returns ``found=True, readable=False`` — never an exception, and never a
    silent "nothing to report".
    """
    if not path.exists():
        return ReviewSummary()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ReviewSummary(found=True, readable=False)
    return _scan(content)


def summary_line_from_candidates(paths: list[Path] | tuple[Path, ...]) -> str:
    """Summarize the first report found among *paths*, in order.

    The caller passes the workspace draft first and the archive second: a task
    whose report has been archived still has one, and reporting "未审查" for it
    would be wrong.
    """
    for path in paths:
        summary = parse_review_report(path)
        if summary.found:
            return _render(summary)
    return "review: 未审查"


def _render(summary: ReviewSummary) -> str:
    if not summary.readable:
        return "review: 报告无法读取（文件存在但打不开，检查权限）"
    if not summary.parsed:
        return "review: 报告存在但无法解析（有分节，但没有可识别的 finding 条目）"
    return f"review: {summary.high} high / {summary.medium} medium / {summary.low} low"


def summary_line(path: Path) -> str:
    """One human-readable line for the status command."""
    return summary_line_from_candidates([path])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point so ``/devflow status`` can call this from Bash.

    Printing the line is the whole contract; the calling command reproduces it
    verbatim rather than re-deriving the counts in prose.
    """
    parser = argparse.ArgumentParser(description="Summarize a DevFlow review report.")
    parser.add_argument(
        "--report",
        required=True,
        action="append",
        help="path to review-report.md; repeat for fallbacks (workspace first, archive second)",
    )
    args = parser.parse_args(argv)
    print(summary_line_from_candidates([Path(p) for p in args.report]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
