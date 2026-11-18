"""Contract tests for the two recall points (ADR-0006, P1).

``召回`` is the "use it back on yourself" half of self-evolution. Without a
pinned contract it decays silently: the section gets dropped from the template,
the trigger table disappears from SKILL.md, and nothing breaks until someone
notices the same pit has been stepped in twice.

These tests pin the *structure* of the contract — where recall is written and
which events trigger it — not the prose. They are deliberately shallow greps
so that rewording is free while removal is caught.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "core" / "orchestrator" / "SKILL.md"
CARD = ROOT / "core" / "templates" / "task-card.md"
START = ROOT / "commands" / "start.md"
FIX = ROOT / "commands" / "fix.md"


class RecallContractTest(unittest.TestCase):
    def test_skill_defines_both_recall_timings(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("设计时", text)
        self.assertIn("开发时", text)
        self.assertIn("memorant_recall", text)

    def test_skill_pins_the_four_development_triggers(self):
        text = SKILL.read_text(encoding="utf-8")
        for trigger in ("测试", "verifier", "首次修改", "新依赖"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, text, f"recall trigger missing from SKILL: {trigger}")

    def test_skill_requires_trust_tier_to_be_shown(self):
        """A recalled memory's trust level must travel with it; feeding a
        provisional (or overturned) memory back as truth is the worst failure
        mode of recall."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("trust_tier", text)
        self.assertIn("verified", text)
        self.assertIn("provisional", text)

    def test_card_template_has_both_recall_sections(self):
        text = CARD.read_text(encoding="utf-8")
        self.assertIn("历史经验", text)
        self.assertIn("踩坑记录", text)

    def test_card_history_section_carries_trust_column(self):
        text = CARD.read_text(encoding="utf-8")
        history = text.split("## 历史经验", 1)
        self.assertEqual(len(history), 2, "历史经验 section is missing")
        section = history[1].split("## ", 1)[0]
        self.assertIn("信任级别", section)

    def test_start_command_recalls_before_writing_the_card(self):
        text = START.read_text(encoding="utf-8")
        self.assertIn("设计时召回", text)
        self.assertIn("plan_pattern", text)
        # Recall must precede the card write, not follow it.
        self.assertLess(text.index("设计时召回"), text.index("写 `.devflow/card.md`"))

    def test_fix_command_has_the_same_recall_points(self):
        text = FIX.read_text(encoding="utf-8")
        self.assertIn("设计时召回", text)
        self.assertIn("plan_pattern", text)
        self.assertIn("bug_pattern", text)

    def test_write_back_happens_at_exactly_two_points(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("GATE-2 方案卡批准时", text)
        self.assertIn("task 完成时", text)


if __name__ == "__main__":
    unittest.main()
