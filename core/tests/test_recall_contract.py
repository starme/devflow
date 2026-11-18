"""Contract tests for the recall points and the ADR-0006 lean shape.

``召回`` is the "use it back on yourself" half of self-evolution. Without a
pinned contract it decays silently: the section gets dropped from the template,
the trigger table disappears from SKILL.md, and nothing breaks until someone
notices the same pit has been stepped in twice.

These tests pin the *structure* of the contract — where recall is written and
which events trigger it — not the prose. They are deliberately shallow greps
so that rewording is free while removal is caught.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "core" / "orchestrator" / "SKILL.md"
PLAN = ROOT / "core" / "templates" / "plan.md"
WORKFLOW = ROOT / "commands" / "workflow.md"
COMMANDS = ROOT / "commands"


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

    def test_plan_template_has_both_recall_sections(self):
        text = PLAN.read_text(encoding="utf-8")
        self.assertIn("历史经验", text)
        self.assertIn("踩坑记录", text)

    def test_plan_history_section_carries_trust_column(self):
        text = PLAN.read_text(encoding="utf-8")
        history = text.split("## 4. 历史经验", 1)
        self.assertEqual(len(history), 2, "历史经验 section is missing")
        section = history[1].split("## ", 1)[0]
        self.assertIn("信任级别", section)

    def test_workflow_recalls_before_writing_the_plan(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("设计时召回", text)
        self.assertIn("plan_pattern", text)
        # Recall must precede the plan write, not follow it.
        self.assertLess(text.index("设计时召回"), text.index("写 `.devflow/plan.md`"))

    def test_workflow_covers_both_paths(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("bug_pattern", text)
        self.assertIn("devflow-reviewer", text)

    def test_write_back_happens_at_exactly_two_points(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("GATE-PLAN 批准时", text)
        self.assertIn("task 完成时", text)


class LeanShapeTest(unittest.TestCase):
    """ADR-0006 D1/D3/D5/D6: the flow got simpler, not just differently worded.

    These pin the shape so a later edit cannot quietly reintroduce the second
    demand-side gate or drop the no-spread rule.
    """

    def test_state_machine_has_five_phases(self):
        text = SKILL.read_text(encoding="utf-8")
        for phase in ("`qa`", "`plan_review`", "`working`", "`deliver_confirm`", "`done`"):
            self.assertIn(phase, text)
        self.assertIn("5 个值", text)

    def test_no_feature_path_writes_a_separate_prd(self):
        """D1 merged PRD into the plan document; the workflow must not send the
        model back to ``.devflow/prd.md``."""
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn(".devflow/prd.md", text)
        self.assertNotIn(".devflow/card.md", text)

    def test_plan_template_requires_alternatives(self):
        """D1: 'a mature technical plan' is only checkable if the document has
        to justify what it rejected."""
        text = PLAN.read_text(encoding="utf-8")
        self.assertIn("备选方案与否决理由", text)
        self.assertIn("至少两个", text)

    def test_skill_enforces_no_spread(self):
        """D3: the discipline was entirely missing before ADR-0006."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("不扩散", text)
        self.assertIn("待办支线", text)

    def test_reviewer_agent_exists_and_is_not_a_gate(self):
        """D5: review produces a report for the user to act on; blocking on it
        would put a third gate back into the flow."""
        reviewer = ROOT / "agents" / "reviewer-agent.md"
        self.assertTrue(reviewer.is_file(), "reviewer agent is missing")
        self.assertIn("不阻塞", SKILL.read_text(encoding="utf-8"))
        self.assertIn("review", reviewer.read_text(encoding="utf-8"))

    def test_start_and_fix_share_one_command_file(self):
        """D6: the two paths differed by a branch prefix and one section."""
        self.assertFalse((COMMANDS / "start.md").exists())
        self.assertFalse((COMMANDS / "fix.md").exists())
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("feature", text)
        self.assertIn("bugfix", text)


class RetiredTemplateTest(unittest.TestCase):
    """prd.md and task-card.md were merged into plan.md by ADR-0006 D1.

    They stay in ``core/templates/`` because ``/devflow init`` and the adapter
    docs name them, and old tasks read them — but a file that still teaches
    GATE-1/GATE-2 to whoever opens it is worse than no file. Each must say at
    the top that it is retired and point at the replacement.
    """

    def test_retired_templates_announce_their_successor(self):
        for name in ("prd.md", "task-card.md"):
            with self.subTest(name=name):
                text = (ROOT / "core" / "templates" / name).read_text(encoding="utf-8")
                head = text[:600]
                self.assertIn("已退役", head, f"{name} does not announce retirement")
                self.assertIn("plan.md", head, f"{name} does not point at plan.md")

    def test_flow_points_at_plan_template(self):
        for rel in ("core/orchestrator/SKILL.md", "commands/workflow.md"):
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn("core/templates/plan.md", text)

    def test_init_checks_the_live_template(self):
        text = (ROOT / "commands" / "init.md").read_text(encoding="utf-8")
        self.assertIn("core/templates/plan.md", text)


class ArtifactWiringTest(unittest.TestCase):
    """The new artifacts must reach delivery, not just exist on disk.

    A plan document the commit whitelist does not recognise, or an archive
    step that never copies the review report, silently loses the very record
    the user asked to keep.
    """

    def test_delivery_and_guard_whitelists_agree_on_new_artifacts(self):
        sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
        sys.path.insert(0, str(ROOT / "core" / "hooks"))
        from delivery import DELIVERY_ARTIFACT_FILES
        from devflow_guard_common import _DEVFLOW_ARTIFACT_FILES

        for entry in (".devflow/plan.md", ".devflow/review-report.md"):
            with self.subTest(entry=entry):
                self.assertIn(entry, DELIVERY_ARTIFACT_FILES)
                self.assertIn(entry, _DEVFLOW_ARTIFACT_FILES)

    def test_publish_whitelist_includes_plan_and_review(self):
        sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
        from artifact_publish import PUBLISHABLE_ARTIFACTS

        for name in ("plan.md", "review-report.md"):
            with self.subTest(name=name):
                self.assertIn(name, PUBLISHABLE_ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
