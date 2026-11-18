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


class SubagentDispatchTest(unittest.TestCase):
    """Two defects found by the 2026-11 end-to-end dogfood, both blocking.

    Dispatch naming: the flow text said "派 `devflow-verifier`", but this
    host resolves plugin subagents under a namespace. The bare name fails with
    ``Agent type 'devflow-verifier' not found``, which kills the QA step —
    and review would die the same way one step later.

    Artifact location: ``create_task`` writes ``task.yaml`` into the project
    root, while the flow text said artifacts live "relative to the workspace".
    In a self-hosted repo those are different directories, so the plan
    document landed somewhere ``artifact_publish`` never looks.
    """

    def test_dispatch_uses_the_namespaced_agent_name(self):
        for rel in ("core/orchestrator/SKILL.md", "commands/workflow.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for agent in ("verifier", "reviewer"):
                with self.subTest(rel=rel, agent=agent):
                    self.assertIn(f"devflow:devflow-{agent}", text, f"{rel} must dispatch by namespace")

    def test_flow_states_artifacts_live_beside_task_yaml(self):
        """One rule, stated once: wherever ``task.yaml`` is, the process
        artifacts are its sibling. Anything vaguer ("relative to the
        workspace") reads as the checkout directory and splits the two."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("task.yaml", text)
        self.assertIn("同级", text)


class ReviewLoopTest(unittest.TestCase):
    """Review round 2 was blocked by the permission classifier as
    self-approval: the flow had the implementer dispatch its own re-review and
    consume the verdict with no human in between.

    The fix is not to forbid re-review — it is to make the human the one who
    decides whether a second round is worth running, and to make the second
    round's findings land in front of that human rather than being applied
    automatically.
    """

    def test_review_is_a_human_decision_point(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("review", text)
        # The rule: after review, the user decides. A re-review is the user's
        # call, not the implementer's.
        self.assertIn("由用户决定", text)

    def test_second_review_round_requires_the_user(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("第二轮", text, "SKILL must say who authorises a second review round")


class DraftArtifactTest(unittest.TestCase):
    """``render_task_yaml`` still emitted ``prd``/``card`` keys from v2 while
    the flow had moved to ``plan.md`` — the plan had no slot at all, so every
    new task.yaml pointed ``artifacts`` at files that would never exist."""

    def test_task_yaml_has_a_plan_slot(self):
        sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
        from task_state import TaskRecord, render_task_yaml

        rendered = render_task_yaml(
            TaskRecord(
                task_id="t-1",
                slug="t",
                kind="feature",
                description="d",
                base_ref="main",
                base_commit="abc",
                branch="feature/t",
                worktree="/tmp/t",
            )
        )
        self.assertIn("plan:", rendered)
        self.assertIn(".devflow/plan.md", rendered)

    def test_retired_slots_are_gone(self):
        sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
        from task_state import TaskRecord, render_task_yaml

        rendered = render_task_yaml(
            TaskRecord(
                task_id="t-1",
                slug="t",
                kind="feature",
                description="d",
                base_ref="main",
                base_commit="abc",
                branch="feature/t",
                worktree="/tmp/t",
            )
        )
        self.assertNotIn("prd:", rendered)
        self.assertNotIn("card:", rendered)


class StatusPathCandidatesTest(unittest.TestCase):
    """``status`` asked for the workspace path and the archive path, but not
    the project-root ``.devflow/`` — the very place the dogfood run put its
    report. The candidate set has to cover where artifacts can actually be."""

    def test_status_covers_project_root_devflow(self):
        text = (ROOT / "commands" / "status.md").read_text(encoding="utf-8")
        self.assertIn("project_root", text)
        self.assertGreaterEqual(text.count("--report"), 3, "expect workspace, project root and archive")


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
