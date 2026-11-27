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
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "core" / "orchestrator" / "SKILL.md"
PLAN = ROOT / "core" / "templates" / "plan.md"
WORKFLOW = ROOT / "commands" / "workflow.md"
COMMANDS = ROOT / "commands"



def test_skill_defines_both_recall_timings():
    text = SKILL.read_text(encoding="utf-8")
    assert "设计时" in text
    assert "开发时" in text
    assert "memorant_recall" in text


@pytest.mark.parametrize("trigger", ("测试", "verifier", "首次修改", "新依赖"))
def test_skill_pins_the_four_development_triggers(trigger):
    text = SKILL.read_text(encoding="utf-8")
    assert trigger in text, f"recall trigger missing from SKILL: {trigger}"


def test_skill_requires_trust_tier_to_be_shown():
    """A recalled memory's trust level must travel with it; feeding a
    provisional (or overturned) memory back as truth is the worst failure
    mode of recall."""
    text = SKILL.read_text(encoding="utf-8")
    assert "trust_tier" in text
    assert "verified" in text
    assert "provisional" in text


def test_plan_template_has_both_recall_sections():
    text = PLAN.read_text(encoding="utf-8")
    assert "历史经验" in text
    assert "踩坑记录" in text


def test_plan_history_section_carries_trust_column():
    text = PLAN.read_text(encoding="utf-8")
    history = text.split("## 4. 历史经验", 1)
    assert len(history) == 2, "历史经验 section is missing"
    section = history[1].split("## ", 1)[0]
    assert "信任级别" in section


def test_workflow_recalls_before_writing_the_plan():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "设计时召回" in text
    assert "plan_pattern" in text
    # Recall must precede the plan write, not follow it.
    assert text.index("设计时召回") < text.index("写 `.devflow/plan.md`")


def test_workflow_covers_both_paths():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "bug_pattern" in text
    assert "devflow-reviewer" in text


def test_write_back_happens_at_exactly_two_points():
    text = SKILL.read_text(encoding="utf-8")
    assert "GATE-PLAN 批准时" in text
    assert "task 完成时" in text


def test_state_machine_has_five_phases():
    text = SKILL.read_text(encoding="utf-8")
    for phase in ("`qa`", "`plan_review`", "`working`", "`deliver_confirm`", "`done`"):
        assert phase in text
    assert "5 个值" in text


def test_no_feature_path_writes_a_separate_prd():
    """D1 merged PRD into the plan document; the workflow must not send the
    model back to ``.devflow/prd.md``."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert ".devflow/prd.md" not in text
    assert ".devflow/card.md" not in text


def test_plan_template_requires_alternatives():
    """D1: 'a mature technical plan' is only checkable if the document has
    to justify what it rejected."""
    text = PLAN.read_text(encoding="utf-8")
    assert "备选方案与否决理由" in text
    assert "至少两个" in text


def test_skill_enforces_no_spread():
    """D3: the discipline was entirely missing before ADR-0006."""
    text = SKILL.read_text(encoding="utf-8")
    assert "不扩散" in text
    assert "待办支线" in text


def test_reviewer_agent_exists_and_is_not_a_gate():
    """D5: review produces a report for the user to act on; blocking on it
    would put a third gate back into the flow."""
    reviewer = ROOT / "agents" / "reviewer-agent.md"
    assert reviewer.is_file(), "reviewer agent is missing"
    assert "不阻塞" in SKILL.read_text(encoding="utf-8")
    assert "review" in reviewer.read_text(encoding="utf-8")


def test_start_and_fix_share_one_command_file():
    """D6: the two paths differed by a branch prefix and one section."""
    assert not ((COMMANDS / "start.md").exists())
    assert not ((COMMANDS / "fix.md").exists())
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "feature" in text
    assert "bugfix" in text


@pytest.mark.parametrize("name", ("prd.md", "task-card.md"))
def test_retired_templates_announce_their_successor(name):
    text = (ROOT / "core" / "templates" / name).read_text(encoding="utf-8")
    head = text[:600]
    assert "已退役" in head, f"{name} does not announce retirement"
    assert "plan.md" in head, f"{name} does not point at plan.md"


@pytest.mark.parametrize("rel", ("core/orchestrator/SKILL.md", "commands/workflow.md"))
def test_flow_points_at_plan_template(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "core/templates/plan.md" in text


def test_init_checks_the_live_template():
    text = (ROOT / "commands" / "init.md").read_text(encoding="utf-8")
    assert "core/templates/plan.md" in text


@pytest.mark.parametrize("rel", ("core/orchestrator/SKILL.md", "commands/workflow.md"))
@pytest.mark.parametrize("agent", ("verifier", "reviewer"))
def test_dispatch_uses_the_namespaced_agent_name(rel, agent):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert f"devflow:devflow-{agent}" in text, f"{rel} must dispatch by namespace"


def test_flow_states_artifacts_live_beside_task_yaml():
    """One rule, stated once: wherever ``task.yaml`` is, the process
    artifacts are its sibling. Anything vaguer ("relative to the
    workspace") reads as the checkout directory and splits the two."""
    text = SKILL.read_text(encoding="utf-8")
    assert "task.yaml" in text
    assert "同级" in text


def test_review_is_a_human_decision_point():
    text = SKILL.read_text(encoding="utf-8")
    assert "review" in text
    # The rule: after review, the user decides. A re-review is the user's
    # call, not the implementer's.
    assert "由用户决定" in text


def test_second_review_round_requires_the_user():
    text = SKILL.read_text(encoding="utf-8")
    assert "第二轮" in text, "SKILL must say who authorises a second review round"


def test_task_yaml_has_a_plan_slot():
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
            working_dir="/tmp/t",
        )
    )
    assert "plan:" in rendered
    assert ".devflow/plan.md" in rendered


def test_retired_slots_are_gone():
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
            working_dir="/tmp/t",
        )
    )
    assert "prd:" not in rendered
    assert "card:" not in rendered


def test_status_covers_project_root_devflow():
    text = (ROOT / "commands" / "status.md").read_text(encoding="utf-8")
    assert "project_root" in text
    assert text.count("--report") >= 3, "expect workspace, project root and archive"


@pytest.mark.parametrize("entry", (".devflow/plan.md", ".devflow/review-report.md"))
def test_delivery_and_guard_whitelists_agree_on_new_artifacts(entry):
    sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
    sys.path.insert(0, str(ROOT / "core" / "hooks"))
    from delivery import DELIVERY_ARTIFACT_FILES
    from devflow_guard_common import _DEVFLOW_ARTIFACT_FILES

    assert entry in DELIVERY_ARTIFACT_FILES
    assert entry in _DEVFLOW_ARTIFACT_FILES


@pytest.mark.parametrize("name", ("plan.md", "review-report.md"))
def test_publish_whitelist_includes_plan_and_review(name):
    sys.path.insert(0, str(ROOT / "core" / "orchestrator"))
    from artifact_publish import PUBLISHABLE_ARTIFACTS

    assert name in PUBLISHABLE_ARTIFACTS

