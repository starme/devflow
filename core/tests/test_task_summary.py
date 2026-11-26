"""Tests for the review-report summary used by /devflow status.

Why this module exists at all: the status command could ask the model to read
the review report and count findings in prose, but that answer is not
reproducible and cannot be checked by a `cmd` acceptance criterion. Parsing
lives in code so the count is the same every time the same file is read.

The core rule under test: **"could not parse" must never look like "found
nothing"**. A status line claiming `0 high / 0 medium / 0 low` when the
reviewer wrote its report in an unexpected shape would tell the user a review
passed when it may have found real problems.
"""

import sys
import tempfile
from pathlib import Path

ORCH = Path(__file__).resolve().parent.parent / "orchestrator"
sys.path.insert(0, str(ORCH))

from task_summary import (
    ReviewSummary,
    parse_review_report,
    summary_line,
    summary_line_from_candidates,
)

SAMPLE = """\
# Review Report — t-1

## Summary
- 审查范围：`git diff abc` + 2 个未跟踪文件
- high: 2 | medium: 1 | low: 0
- 结论：有一处会丢数据

## high
- **未提交即退出** — `delivery.py:42`
  - 为什么是 high：进程退出后改动丢失
  - 建议：先写盘再退出
- **路径未校验** — `publish.py:88`
  - 建议：加 resolve 校验

## medium
- **缺少超时** — `probe.py:12`
  - 建议：加 timeout

## low
（无）

## 已检查但没问题的方面
- 命名
"""


def _write(text):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "review-report.md"
    path.write_text(text, encoding="utf-8")
    return tmp, path


def test_counts_each_severity_section():
    tmp, path = _write(SAMPLE)
    with tmp:
        result = parse_review_report(path)
    assert result.high == 2
    assert result.medium == 1
    assert result.low == 0
    assert result.found


def test_missing_file_is_not_found():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        result = parse_review_report(Path(tmp.name) / "nope.md")
    assert not (result.found)
    assert result.high + result.medium + result.low == 0


def test_unrecognised_shape_is_not_reported_as_zero_findings():
    """The dangerous failure: a report that exists but has no severity
    sections must not be summarised as "nothing to fix"."""
    tmp, path = _write("# Review Report\n\n没有分节，只有一段话。\n")
    with tmp:
        result = parse_review_report(path)
    assert result.found, "file exists, so it was found"
    assert not (result.parsed), "but no severity sections were recognised"


def test_empty_high_section_counts_zero_but_still_parses():
    report = "## high\n（无）\n\n## medium\n- **a** — `f.py:1`\n\n## low\n（无）\n"
    tmp, path = _write(report)
    with tmp:
        result = parse_review_report(path)
    assert result.parsed
    assert (result.high, result.medium, result.low) == (0, 1, 0)


def test_only_bold_list_items_count_as_findings():
    """Prose bullets under a severity heading are explanation, not
    findings; the reviewer template writes findings as `- **...**`."""
    report = "## high\n- 这是一句说明，不是条目\n- **真条目** — `a.py:1`\n\n## medium\n## low\n"
    tmp, path = _write(report)
    with tmp:
        result = parse_review_report(path)
    assert result.high == 1


def test_sections_with_unrecognised_entries_are_not_parsed():
    """Review finding 1: sections present but every entry in a shape the
    parser does not recognise (ordered list, no bold) used to set
    ``parsed=True`` and print ``0 high / 0 medium / 0 low`` — the exact
    lie the module exists to prevent."""
    report = "## high\n1. 未加粗的条目 a.py:1\n2. 另一条 b.py:2\n\n## medium\n- 说明文字\n"
    tmp, path = _write(report)
    with tmp:
        result = parse_review_report(path)
    assert result.found
    assert not (result.parsed), "no findings recognised, so it cannot claim zero"


def test_a_mix_of_recognised_and_unrecognised_still_parses():
    """One recognisable finding is enough: the parser is not all-or-nothing
    per section, it reports what it could actually read."""
    report = "## high\n1. 未识别\n- **识别到** — `a.py:1`\n"
    tmp, path = _write(report)
    with tmp:
        result = parse_review_report(path)
    assert result.parsed
    assert result.high == 1


def test_explicitly_empty_sections_parse_as_zero():
    """An empty section is a real statement ("nothing here"), unlike a
    section full of entries the parser could not read."""
    report = "## high\n（无）\n\n## medium\n（无）\n\n## low\n（无）\n"
    tmp, path = _write(report)
    with tmp:
        result = parse_review_report(path)
    assert result.parsed
    assert result.total == 0


def test_line_reports_counts():
    tmp, path = _write(SAMPLE)
    with tmp:
        line = summary_line(path)
    assert "2" in line
    assert "high" in line


def test_missing_report_says_not_reviewed():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        line = summary_line(Path(tmp.name) / "nope.md")
    assert "未审查" in line


def test_unparsed_report_says_so_instead_of_zero():
    tmp, path = _write("# Review Report\n\n一段话，没有分节。\n")
    with tmp:
        line = summary_line(path)
    assert "0 high" not in line
    assert "无法解析" in line


def test_default_summary_is_absent():
    summary = ReviewSummary()
    assert not (summary.found)


def test_unreadable_file_is_distinguished_from_missing():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        path = Path(tmp.name) / "review-report.md"
        path.write_text("## high\n- **x** — `a.py:1`\n", encoding="utf-8")
        path.chmod(0o000)
        try:
            result = parse_review_report(path)
            line = summary_line(path)
        finally:
            path.chmod(0o644)
    assert result.found, "the file exists"
    assert not (result.readable), "but could not be read"
    assert "无法读取" in line


def test_falls_back_to_the_archive_path():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        worktree = Path(tmp.name) / "wt"
        archive = Path(tmp.name) / "tasks" / "t-1"
        archive.mkdir(parents=True)
        (archive / "review-report.md").write_text(
            "## high\n- **x** — `a.py:1`\n", encoding="utf-8"
        )
        line = summary_line_from_candidates(
            [worktree / ".devflow" / "review-report.md", archive / "review-report.md"]
        )
    assert "1 high" in line


def test_workspace_wins_when_both_exist():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        worktree = Path(tmp.name) / "wt"
        worktree.mkdir()
        archive = Path(tmp.name) / "tasks" / "t-1"
        archive.mkdir(parents=True)
        (worktree / "review-report.md").write_text(
            "## high\n- **a** — `a.py:1`\n\n## medium\n- **b** — `b.py:1`\n",
            encoding="utf-8",
        )
        (archive / "review-report.md").write_text(
            "## high\n- **x** — `a.py:1`\n", encoding="utf-8"
        )
        line = summary_line_from_candidates(
            [worktree / "review-report.md", archive / "review-report.md"]
        )
    assert "1 high" in line
    assert "1 medium" in line


def test_all_paths_missing_says_not_reviewed():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        line = summary_line_from_candidates([Path(tmp.name) / "a.md", Path(tmp.name) / "b.md"])
    assert "未审查" in line


def _run(*args):
    import subprocess

    return subprocess.run(
        [sys.executable, str(ORCH / "task_summary.py"), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_prints_counts():
    tmp, path = _write(SAMPLE)
    with tmp:
        proc = _run("--report", str(path))
    assert proc.returncode == 0
    assert "2 high" in proc.stdout


def test_cli_prints_not_reviewed_for_missing_file():
    tmp = tempfile.TemporaryDirectory()
    with tmp:
        proc = _run("--report", str(Path(tmp.name) / "nope.md"))
    assert "未审查" in proc.stdout


def test_cli_requires_report_argument():
    proc = _run()
    assert proc.returncode != 0

