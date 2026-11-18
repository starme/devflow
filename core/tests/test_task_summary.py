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
import unittest
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


class ParseReviewReportTest(unittest.TestCase):
    def test_counts_each_severity_section(self):
        tmp, path = _write(SAMPLE)
        with tmp:
            result = parse_review_report(path)
        self.assertEqual(result.high, 2)
        self.assertEqual(result.medium, 1)
        self.assertEqual(result.low, 0)
        self.assertTrue(result.found)

    def test_missing_file_is_not_found(self):
        tmp = tempfile.TemporaryDirectory()
        with tmp:
            result = parse_review_report(Path(tmp.name) / "nope.md")
        self.assertFalse(result.found)
        self.assertEqual(result.high + result.medium + result.low, 0)

    def test_unrecognised_shape_is_not_reported_as_zero_findings(self):
        """The dangerous failure: a report that exists but has no severity
        sections must not be summarised as "nothing to fix"."""
        tmp, path = _write("# Review Report\n\n没有分节，只有一段话。\n")
        with tmp:
            result = parse_review_report(path)
        self.assertTrue(result.found, "file exists, so it was found")
        self.assertFalse(result.parsed, "but no severity sections were recognised")

    def test_empty_high_section_counts_zero_but_still_parses(self):
        report = "## high\n（无）\n\n## medium\n- **a** — `f.py:1`\n\n## low\n（无）\n"
        tmp, path = _write(report)
        with tmp:
            result = parse_review_report(path)
        self.assertTrue(result.parsed)
        self.assertEqual((result.high, result.medium, result.low), (0, 1, 0))

    def test_only_bold_list_items_count_as_findings(self):
        """Prose bullets under a severity heading are explanation, not
        findings; the reviewer template writes findings as `- **...**`."""
        report = "## high\n- 这是一句说明，不是条目\n- **真条目** — `a.py:1`\n\n## medium\n## low\n"
        tmp, path = _write(report)
        with tmp:
            result = parse_review_report(path)
        self.assertEqual(result.high, 1)

    def test_sections_with_unrecognised_entries_are_not_parsed(self):
        """Review finding 1: sections present but every entry in a shape the
        parser does not recognise (ordered list, no bold) used to set
        ``parsed=True`` and print ``0 high / 0 medium / 0 low`` — the exact
        lie the module exists to prevent."""
        report = "## high\n1. 未加粗的条目 a.py:1\n2. 另一条 b.py:2\n\n## medium\n- 说明文字\n"
        tmp, path = _write(report)
        with tmp:
            result = parse_review_report(path)
        self.assertTrue(result.found)
        self.assertFalse(result.parsed, "no findings recognised, so it cannot claim zero")

    def test_a_mix_of_recognised_and_unrecognised_still_parses(self):
        """One recognisable finding is enough: the parser is not all-or-nothing
        per section, it reports what it could actually read."""
        report = "## high\n1. 未识别\n- **识别到** — `a.py:1`\n"
        tmp, path = _write(report)
        with tmp:
            result = parse_review_report(path)
        self.assertTrue(result.parsed)
        self.assertEqual(result.high, 1)

    def test_explicitly_empty_sections_parse_as_zero(self):
        """An empty section is a real statement ("nothing here"), unlike a
        section full of entries the parser could not read."""
        report = "## high\n（无）\n\n## medium\n（无）\n\n## low\n（无）\n"
        tmp, path = _write(report)
        with tmp:
            result = parse_review_report(path)
        self.assertTrue(result.parsed)
        self.assertEqual(result.total, 0)


class SummaryLineTest(unittest.TestCase):
    def test_line_reports_counts(self):
        tmp, path = _write(SAMPLE)
        with tmp:
            line = summary_line(path)
        self.assertIn("2", line)
        self.assertIn("high", line)

    def test_missing_report_says_not_reviewed(self):
        tmp = tempfile.TemporaryDirectory()
        with tmp:
            line = summary_line(Path(tmp.name) / "nope.md")
        self.assertIn("未审查", line)

    def test_unparsed_report_says_so_instead_of_zero(self):
        tmp, path = _write("# Review Report\n\n一段话，没有分节。\n")
        with tmp:
            line = summary_line(path)
        self.assertNotIn("0 high", line)
        self.assertIn("无法解析", line)


class ReviewSummaryShapeTest(unittest.TestCase):
    def test_default_summary_is_absent(self):
        summary = ReviewSummary()
        self.assertFalse(summary.found)


class UnreadableFileTest(unittest.TestCase):
    """Review finding low#4: "cannot read" collapsed into "does not exist".

    The status line said 未审查 for both, which hides a permissions problem as
    if no review had been run.
    """

    def test_unreadable_file_is_distinguished_from_missing(self):
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
        self.assertTrue(result.found, "the file exists")
        self.assertFalse(result.readable, "but could not be read")
        self.assertIn("无法读取", line)


class MultiPathTest(unittest.TestCase):
    """Review finding 2: the plan recalled that a report may live in the task
    archive as well as the workspace. Checking only the workspace reports
    "未审查" for a task whose report has been archived."""

    def test_falls_back_to_the_archive_path(self):
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
        self.assertIn("1 high", line)

    def test_workspace_wins_when_both_exist(self):
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
        self.assertIn("1 high", line)
        self.assertIn("1 medium", line)

    def test_all_paths_missing_says_not_reviewed(self):
        tmp = tempfile.TemporaryDirectory()
        with tmp:
            line = summary_line_from_candidates([Path(tmp.name) / "a.md", Path(tmp.name) / "b.md"])
        self.assertIn("未审查", line)


class CliTest(unittest.TestCase):
    """``/devflow status`` calls this from Bash, so the CLI is the interface
    the flow depends on — not just the functions."""

    def _run(self, *args):
        import subprocess

        return subprocess.run(
            [sys.executable, str(ORCH / "task_summary.py"), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_prints_counts(self):
        tmp, path = _write(SAMPLE)
        with tmp:
            proc = self._run("--report", str(path))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("2 high", proc.stdout)

    def test_cli_prints_not_reviewed_for_missing_file(self):
        tmp = tempfile.TemporaryDirectory()
        with tmp:
            proc = self._run("--report", str(Path(tmp.name) / "nope.md"))
        self.assertIn("未审查", proc.stdout)

    def test_cli_requires_report_argument(self):
        proc = self._run()
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
