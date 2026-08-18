import asyncio
from collections.abc import Iterator

import pytest

from app.workflows.digest.common.models import DigestMaterialContext, DigestMode, DigestModeDecision
from app.workflows.digest.planner.lib.constants import get_planner_mode_contract
from app.workflows.digest.planner.lib.model_policy import PlannerModelStep, planner_completion_kwargs
from app.workflows.digest.planner.lib.plans import (
    compose_effective_planner_request_text,
    normalize_planner_diagnosis_draft,
    normalize_planner_draft,
)
from app.workflows.digest.planner.lib.store import _ensure_chapter_count_payload
from app.workflows.digest.docgen.nodes.load_context import _render_diagnose_brief
from app.workflows.digest.planner.nodes import compose_planner_draft as plan_draft_node
from app.workflows.digest.planner.nodes import understand_goal_and_materials as understand_node
import app.workflows.digest.planner.prompts.build_plan_composer as planner_prompt_module
from app.workflows.digest.planner.nodes.save_planner_draft import (
    _merge_diagnose_resolution,
    _resolve_effective_course_name,
)
from app.workflows.digest.planner.prompts.build_plan_composer import (
    BUILD_CONSTRAINTS_END,
    BUILD_CONSTRAINTS_START,
    CHAPTERS_END,
    CHAPTERS_START,
    COURSE_NAME_END,
    COURSE_NAME_START,
    DIAGNOSE_END,
    DIAGNOSE_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
    build_planner_diagnosis_messages,
    build_planner_diagnosis_repair_messages,
    build_planner_repair_messages,
    build_planner_stream_messages,
)


def _material_context() -> DigestMaterialContext:
    return DigestMaterialContext(
        course_mode_decision=DigestModeDecision(mode=DigestMode.SPRINT),
        material_digest="高数速成资料摘要，重点覆盖极限、导数和积分。",
    )


def _planner_payload(*, chapter_count: int = 3) -> dict[str, object]:
    return {
        "course_name": "高数主线重建",
        "course_icon": "sigma",
        "planning_note": "用户想把高数混乱知识整理成可执行复习路径。\n资料显示当前重点集中在极限、导数和积分。",
        "suggestion": "如果更偏考试，可以增加题型和易错点密度。",
        "plan": "本课程会先用极限建立函数变化的基础，再进入导数规则与应用，最后把积分计算和综合题串起来。",
        "diagnose": [
            {
                "question": "极限、导数、积分里你现在最怕哪一块？",
                "purpose": "识别高数复习的第一薄弱入口。",
                "options": ["极限定义", "导数应用", "积分计算", "综合应用"],
            }
        ],
        "chapters": [
            {
                "title": f"任务切片 {index}",
                "objective": f"理解并完成切片 {index} 的学习任务。",
                "required_elements": [f"切片 {index} 的学习任务", f"切片 {index} 的边界"],
            }
            for index in range(1, chapter_count + 1)
        ],
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"planner_operation": "create"}, True),
        ({"planner_operation": "create", "latest_plan": {"chapters": []}}, False),
        ({"planner_operation": "create", "diagnose_status": "answered"}, False),
        ({"planner_operation": "append", "refresh_diagnosis": False}, False),
        ({"planner_operation": "append", "refresh_diagnosis": True}, True),
    ],
)
def test_planner_diagnosis_generation_decision(
    state: dict[str, object],
    expected: bool,
) -> None:
    assert plan_draft_node._should_generate_diagnosis_first(state) is expected


def test_refreshed_diagnosis_uses_current_revision_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    questions = [
        {
            "question": f"诊断问题 {index}",
            "purpose": "用于调整正式方案。",
            "options": ["选项 A", "选项 B", "选项 C", "选项 D"],
        }
        for index in range(1, 5)
    ]

    def fake_build_messages(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return [{"role": "user", "content": "diagnosis"}]

    async def fake_stream(_state, *, messages):
        captured["messages"] = messages
        return "diagnosis-output"

    async def fake_emit_event(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(plan_draft_node, "build_planner_diagnosis_messages", fake_build_messages)
    monkeypatch.setattr(plan_draft_node, "_stream_diagnosis_response", fake_stream)
    monkeypatch.setattr(plan_draft_node, "_parse_generated_course_name", lambda _output: "高数六章精讲")
    monkeypatch.setattr(plan_draft_node, "_parse_diagnosis_response", lambda _output: questions)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "planner_operation": "append",
                "refresh_diagnosis": True,
                "material_context": _material_context(),
                "planning_note": "原方案为四章。",
                "material_note": "没有上传资料。",
                "user_prompt": "请生成四章高数课程。",
                "feedback_message": "改为严格六章，并刷新前置诊断。",
                "digest_mode": "sprint",
                "message_history": [],
                "latest_plan": {"course_name": "高数四章", "user_prompt": "请生成四章高数课程。"},
            }
        )
    )

    effective_request = "请生成四章高数课程。\n用户最新调整：改为严格六章，并刷新前置诊断。"
    assert captured["user_prompt"] == effective_request
    assert captured["messages"] == [{"role": "user", "content": "diagnosis"}]
    assert result["build_plan_draft"]["user_prompt"] == effective_request.replace("\n", " ")


def test_planner_plan_contract_is_lightweight_and_leaves_execution_strategy_to_docgen() -> None:
    messages = build_planner_stream_messages(
        course_name="高等数学",
        user_prompt="系统学习极限、导数和积分",
        digest_mode="systematic",
        material_context=_material_context(),
        planning_note="覆盖极限、导数和积分。",
        material_note="没有上传资料。",
        message_history=[],
    )
    prompt_text = "\n".join(message["content"] for message in messages)

    assert '"required_elements"' in prompt_text
    assert '"writing_instructions"' not in prompt_text
    assert planner_completion_kwargs(PlannerModelStep.DRAFT_PLAN)["max_tokens"] == 4800
    assert planner_completion_kwargs(PlannerModelStep.REPAIR_PLAN)["max_tokens"] == 4800


def test_normalize_planner_draft_uses_new_planner_fields() -> None:
    draft = normalize_planner_draft(
        _planner_payload(),
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "高数主线重建"
    assert draft.course_icon == "sigma"
    assert draft.planning_note.startswith("用户想把高数")
    assert "资料显示" in draft.planning_note
    assert draft.suggestion.startswith("如果更偏考试")
    assert draft.plan.startswith("本课程会先用极限")
    assert [chapter.title for chapter in draft.chapters] == ["任务切片 1", "任务切片 2", "任务切片 3"]
    assert all(chapter.writing_instructions == "" for chapter in draft.chapters)
    assert draft.diagnose[0].question == "极限、导数、积分里你现在最怕哪一块？"
    assert draft.diagnose[0].options == ["极限定义", "导数应用", "积分计算", "综合应用"]


def test_normalize_planner_draft_rejects_ocr_fragments_in_required_elements() -> None:
    payload = _planner_payload()
    payload["chapters"][0]["required_elements"] = [
        "变量定义、初始化与赋值",
        "| int | a,b,c; | --- | --- | " + "破碎表格与 OCR 内容" * 20,
        "```c int main(void) { return 0; } ```",
    ]

    with pytest.raises(ValueError, match="non-concise required_element"):
        normalize_planner_draft(
            payload,
            course_id="C 语言",
            user_prompt="学习 C 语言",
            requested_digest_mode="sprint",
        )


def test_normalize_planner_draft_does_not_replace_ocr_fragments_with_local_semantics() -> None:
    payload = _planner_payload()
    payload["chapters"][0]["required_elements"] = ["| --- | " + "OCR 碎片" * 50]

    with pytest.raises(ValueError, match="non-concise required_element"):
        normalize_planner_draft(
            payload,
            course_id="高数",
            user_prompt="高数速成",
            requested_digest_mode="sprint",
        )


def test_normalize_planner_draft_preserves_model_diagnosis_semantics() -> None:
    payload = _planner_payload()
    payload["diagnose"] = [
        {
            "question": "图示辅助的重点？",
            "purpose": "影响章节的图示重点。",
            "options": ["图示辅助", "基础计算", "综合应用", "少用图示"],
        }
    ]

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert draft.diagnose[0].question == "图示辅助的重点？"
    assert draft.diagnose[0].purpose == "影响章节的图示重点。"
    assert draft.diagnose[0].options == ["图示辅助", "基础计算", "综合应用", "少用图示"]


def test_diagnose_resolution_merges_answers_into_latest_questions() -> None:
    current_plan = _planner_payload()
    current_plan["diagnose"] = [
        {
            "question": "模型重新生成的新问题",
            "purpose": "不应该覆盖用户已看到的问题。",
            "options": ["新选项"],
        }
    ]
    state = {
        "latest_plan": _planner_payload(),
        "diagnose_answers": [
            {
                "question": "极限、导数、积分里你现在最怕哪一块？",
                "answer": "导数应用",
            }
        ],
        "diagnose_status": "answered",
        "diagnose_note": "先补导数，再串积分。",
    }

    merged = _merge_diagnose_resolution(current_plan, state)

    assert merged["diagnose"][0]["question"] == "极限、导数、积分里你现在最怕哪一块？"
    assert merged["diagnose"][0]["answer"] == "导数应用"
    assert merged["diagnose_status"] == "answered"
    assert merged["diagnose_note"] == "先补导数，再串积分。"


def test_docgen_diagnose_brief_renders_user_answers() -> None:
    brief = _render_diagnose_brief(
        [
            {
                "question": "你最想先补哪一块？",
                "purpose": "定位优先级。",
                "options": ["函数", "几何"],
                "answer": "函数",
            }
        ],
        status="answered",
        note="希望后续例题对齐函数薄弱点。",
    )

    assert "用户补充：希望后续例题对齐函数薄弱点。" in brief
    assert "用户回答：函数" in brief
    assert "已确认的诊断选择" in brief
    assert "执行策略" not in brief
    assert "硬性生成约束" in brief
    assert "文档内解析方式" in brief
    assert "章末小测配置" in brief
    assert "快速回答" not in brief


def test_understand_goal_and_materials_reuses_prepared_context_without_auxiliary_llms() -> None:
    events: list[dict[str, object]] = []
    tokens: list[str] = []

    async def record_event(payload: dict[str, object]) -> None:
        events.append(payload)

    async def record_token(token: str) -> None:
        tokens.append(token)

    node = understand_node.build_understand_goal_and_materials_node(context=None)
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "planner_test",
                "planner_operation": "create",
                "user_prompt": "两天速成线性代数。",
                "digest_mode": "sprint",
                "material_context": _material_context(),
                "progress_callback": record_event,
                "token_callback": record_token,
            }
        )
    )

    stages = [str(event.get("stage") or "") for event in events]
    assert "两天速成线性代数" in result["planning_note"]
    assert "。。" not in result["planning_note"]
    assert "用户目标" in result["material_note"]
    assert "planner.analysis.started" in stages
    assert "planner.analysis.ready" in stages
    assert "planner.analysis.failed" not in stages
    assert tokens == []


def test_compose_planner_diagnosis_raises_when_stream_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_diagnosis(state, *, messages):
        del state, messages
        raise TimeoutError("diagnosis timed out")

    events: list[dict[str, object]] = []

    async def record_event(payload: dict[str, object]) -> None:
        events.append(payload)

    monkeypatch.setattr(plan_draft_node, "_stream_diagnosis_response", fail_diagnosis)

    node = plan_draft_node.build_compose_planner_draft_node(context=None)
    with pytest.raises(TimeoutError, match="diagnosis timed out"):
        asyncio.run(
            node(
                {
                    "course_id": "course_test",
                    "planner_session_id": "planner_test",
                    "planner_operation": "create",
                    "user_prompt": "两天速成线性代数",
                    "digest_mode": "sprint",
                    "material_context": _material_context(),
                    "planning_note": "需要先建立核心概念和例题路径。",
                    "material_note": "资料重点是矩阵和线性方程组。",
                    "progress_callback": record_event,
                }
            )
        )

    stages = [str(event.get("stage") or "") for event in events]
    assert stages == ["planner.diagnose.failed"]


@pytest.mark.parametrize(
    ("builder", "expected_name"),
    [
        (build_planner_repair_messages, "planner_plan_repair"),
        (build_planner_diagnosis_repair_messages, "planner_diagnosis_repair"),
    ],
)
def test_planner_repair_prompts_are_traced(
    monkeypatch: pytest.MonkeyPatch,
    builder,
    expected_name: str,
) -> None:
    trace_calls: list[dict[str, object]] = []

    def fake_trace_prompt_build(name, *, inputs, output):
        trace_calls.append({"name": name, "inputs": inputs, "output": output})
        return output

    monkeypatch.setattr(planner_prompt_module, "trace_prompt_build", fake_trace_prompt_build)
    messages = builder(
        original_messages=[{"role": "system", "content": "课程上下文"}],
        invalid_output="broken",
        error="invalid format",
    )

    assert trace_calls == [
        {
            "name": expected_name,
            "inputs": {
                "original_message_count": 1,
                "invalid_output_chars": 6,
                "error_chars": 14,
            },
            "output": messages,
        }
    ]


def test_diagnosis_stream_preview_exposes_generated_scope_without_protocol_json() -> None:
    raw_output = (
        f"{COURSE_NAME_START}高等数学期末复习{COURSE_NAME_END}"
        f"{DIAGNOSE_START}"
        '[{"question":"极限与导数基础更需要补哪块？","purpose":"文档落点：调整起点",'
        '"options":["极限","导数","都要","直接练习"]},'
        '{"question":"中值定理与积分怎样分配篇幅？","purpose":"文档落点：调整篇幅"}'
    )

    preview = plan_draft_node._diagnosis_stream_preview(raw_output)

    assert preview == (
        "正在为「高等数学期末复习」准备前置诊断\n\n"
        "1. 极限与导数基础更需要补哪块？\n"
        "2. 中值定理与积分怎样分配篇幅？"
    )
    assert "DIAGNOSE_JSON" not in preview
    assert "purpose" not in preview


def test_diagnosis_prompt_selects_high_impact_course_level_decisions() -> None:
    messages = build_planner_diagnosis_messages(
        course_name="Python 数据处理",
        user_prompt="构建 Python 数据处理课程，覆盖数据清洗、统计分析、可视化和自动化报告。",
        digest_mode="sprint",
        material_context=_material_context(),
        planning_note="面向有基础语法经验的学习者。",
        material_note="没有额外资料。",
        message_history=[],
    )

    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "提炼整门课程的目标、完整范围、主要模块" in system_prompt
    assert "已经明确的内容不要换个说法再次询问" in system_prompt
    assert "信息增益最高的课程级决策" in system_prompt
    assert "四题没有固定题面或固定顺序" in system_prompt
    assert "篇幅与讲解细致程度" in system_prompt
    assert "例题、练习与章末小测密度" in system_prompt
    assert "解析写到什么粒度" in system_prompt
    assert "短标签｜具体影响" in system_prompt
    assert "整个 option 最长不超过 48" in system_prompt
    assert "不能写“不设小测”“取消测试”" in system_prompt
    assert "如果用户已经明确其中某项，就替换" in system_prompt
    assert "个性化应体现在对课程范围的准确概括、模块分组和选项语义上" in system_prompt
    assert "共同覆盖用户列出的全部主要模块" in system_prompt
    assert "不能只列输入靠前的几项" in system_prompt
    assert "极限" not in system_prompt
    assert "洛必达" not in system_prompt
    assert user_prompt.index("用户完整建课目标") < user_prompt.index("当前暂存名称")
    assert "仅在上面的用户目标未提供时参考" in user_prompt


def test_compose_planner_plan_raises_after_generation_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_plan(state, **kwargs):
        del state, kwargs
        raise TimeoutError("plan timed out")

    events: list[dict[str, object]] = []

    async def record_event(payload: dict[str, object]) -> None:
        events.append(payload)

    monkeypatch.setattr(plan_draft_node, "_stream_planner_response", fail_plan)

    node = plan_draft_node.build_compose_planner_draft_node(context=None)
    with pytest.raises(TimeoutError, match="plan timed out"):
        asyncio.run(
            node(
                {
                    "course_id": "course_test",
                    "planner_session_id": "planner_test",
                    "planner_operation": "append",
                    "user_prompt": "请基于每日验收资料生成一个极简学习方案，只需要 2 章。",
                    "feedback_message": "跳过前置诊断，请直接生成正式方案。",
                    "digest_mode": "sprint",
                    "material_context": _material_context(),
                    "planning_note": "需要先建立核心概念和例题路径。",
                    "material_note": "资料重点是极限、导数和积分。",
                    "latest_plan": {
                        "planner_stage": "diagnosis",
                        "course_name": "高数主线重建",
                        "course_icon": "sigma",
                        "user_prompt": "请基于每日验收资料生成一个极简学习方案，只需要 2 章。",
                        "digest_mode": "sprint",
                        "planning_note": "需要先建立核心概念和例题路径。",
                        "diagnose": [
                            {
                                "question": "解析怎么写？",
                                "purpose": "影响正文解析粒度。",
                                "options": ["只给要点", "步骤解析", "错因提醒", "补变式题"],
                            }
                        ],
                        "diagnose_status": "pending",
                        "chapters": [],
                    },
                    "diagnose_status": "skipped",
                    "diagnose_answers": [],
                    "progress_callback": record_event,
                }
            )
        )

    stages = [str(event.get("stage") or "") for event in events]
    assert "planner.plan.failed" in stages
    assert "planner.plan.fallback" not in stages
    assert "planner.plan.ready" not in stages


def test_docgen_diagnose_brief_maps_different_answers_to_different_actions() -> None:
    brief = _render_diagnose_brief(
        [
            {
                "question": "解析怎么写？",
                "purpose": "文档落点：影响文档内例题、练习和章末小测的解析配置。",
                "options": ["只给要点", "写清依据", "补错因提醒", "补变式题"],
                "answer": "写清依据",
            },
            {
                "question": "练习怎么放？",
                "purpose": "文档落点：影响随堂练习和章末小测密度。",
                "options": ["少量精练", "每节小练", "章末小测", "多练变式"],
                "answer": "多练变式",
            },
        ],
        status="answered",
    )

    assert "选择“写清依据”" in brief
    assert "用户回答：写清依据" in brief
    assert "用户回答：多练变式" in brief
    assert "文档落点：影响文档内例题、练习和章末小测的解析配置" in brief
    assert "已确认的诊断选择" in brief
    assert "执行策略：" not in brief


def test_normalize_planner_draft_does_not_build_fallback_diagnose() -> None:
    payload = _planner_payload()
    payload.pop("diagnose")

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="高数速成",
        requested_digest_mode="sprint",
    )

    assert draft.diagnose == []
    assert draft.diagnose_status == ""


def test_normalize_planner_draft_does_not_use_full_prompt_as_course_name() -> None:
    payload = _planner_payload()
    payload.pop("course_name")

    draft = normalize_planner_draft(
        payload,
        course_id="course_titlefallback",
        user_prompt="我想学习初中几何，按平行线与角、三角形全等、圆与切线生成 3 个章节",
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "初中几何"


def test_normalize_planner_draft_preserves_llm_chapters_without_local_merging() -> None:
    config = get_planner_mode_contract("sprint")
    payload = _planner_payload(chapter_count=config.max_chapters + 2)
    payload["plan"] = "这门速成课会先补关键概念，再把典型题串起来。"
    draft = normalize_planner_draft(
        payload,
        course_id="Python数据分析",
        user_prompt="Python 数据分析想学到能做作业",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == config.max_chapters + 2
    assert [chapter.chapter_index for chapter in draft.chapters] == list(range(1, config.max_chapters + 3))
    assert not any("超出章节预算后合并覆盖" in item for item in draft.chapters[-1].required_elements)
    assert "速成课" not in draft.plan
    assert "紧凑节奏" in draft.plan


def test_normalize_planner_draft_respects_user_requested_chapter_count() -> None:
    requested_count = get_planner_mode_contract("sprint").max_chapters + 2
    payload = _planner_payload(chapter_count=requested_count)
    payload["build_constraints"] = {
        "requested_chapter_count": requested_count,
        "chapter_count_source": "user_request",
    }

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="帮我改成定积分的 9 个章节",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == requested_count
    assert draft.build_constraints["requested_chapter_count"] == requested_count
    assert draft.build_constraints["chapter_count_source"] == "user_request"


def test_normalize_planner_draft_rejects_wrong_exact_chapter_count() -> None:
    payload = _planner_payload(chapter_count=5)
    payload.pop("course_name")

    with pytest.raises(ValueError, match="does not match requested 2"):
        normalize_planner_draft(
            payload,
            course_id="course_titlefallback",
            user_prompt="我想学习初中函数，请构建一门 2 章课程，每章要有例题和易错点。",
            requested_digest_mode="sprint",
        )


def test_normalize_planner_draft_prefers_current_request_over_stale_count_constraint() -> None:
    payload = _planner_payload(chapter_count=2)

    draft = normalize_planner_draft(
        payload,
        course_id="course_linear_algebra",
        user_prompt="请把原来的三章方案调整为只有两章。",
        requested_digest_mode="sprint",
        latest_plan={
            "build_constraints": {
                "requested_chapter_count": 3,
                "chapter_count_source": "user_request",
            }
        },
    )

    assert len(draft.chapters) == 2
    assert draft.build_constraints["requested_chapter_count"] == 2


def test_normalize_planner_draft_prefers_latest_exact_count_over_earlier_range() -> None:
    payload = _planner_payload(chapter_count=6)
    request_text = compose_effective_planner_request_text(
        "请生成 3-5 章课程。",
        "请严格调整为 6 章。",
    )

    draft = normalize_planner_draft(
        payload,
        course_id="course_linear_algebra",
        user_prompt=request_text,
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == 6
    assert draft.build_constraints["requested_chapter_count"] == 6
    assert draft.build_constraints.get("requested_chapter_min") is None
    assert draft.build_constraints.get("requested_chapter_max") is None


def test_normalize_planner_draft_prefers_latest_title_list_over_earlier_count() -> None:
    payload = _planner_payload(chapter_count=3)
    request_text = compose_effective_planner_request_text(
        "请生成 6 章课程。",
        "请改为：第 1 章集合，第 2 章函数，第 3 章导数。",
    )

    draft = normalize_planner_draft(
        payload,
        course_id="course_linear_algebra",
        user_prompt=request_text,
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == 3
    assert draft.build_constraints["requested_chapter_count"] == 3


def test_normalize_planner_draft_rejects_wrong_count_from_revision_feedback() -> None:
    payload = _planner_payload(chapter_count=4)
    request_text = compose_effective_planner_request_text(
        "基于上传资料生成一份冲刺复习文档。",
        "跳过诊断。请严格生成 1 章，章节名为：C 指针与变量位置。不要扩展成多章。",
    )

    with pytest.raises(ValueError, match="does not match requested 1"):
        normalize_planner_draft(
            payload,
            course_id="course_smoke",
            user_prompt=request_text,
            requested_digest_mode="sprint",
        )


def test_normalize_planner_draft_ignores_diagnosis_metadata_for_chapter_count() -> None:
    payload = _planner_payload(chapter_count=6)
    original_prompt = "我想系统学习 Python 入门，从变量、条件判断、循环和函数开始。"
    diagnosis_feedback = "\n".join(
        [
            "前置诊断选择：",
            "问题：基础从哪起？",
            "回答：从零环境",
            "落点：文档落点：决定前置概念补多少、第一章铺垫长度、首批代码示例难度。",
            "请根据这些选择更新学习方案，并让后续知识文档的讲解起点、例题、练习和文档内解析对齐这些信号。",
        ]
    )

    assert compose_effective_planner_request_text(original_prompt, diagnosis_feedback) == original_prompt

    draft = normalize_planner_draft(
        payload,
        course_id="course_python",
        user_prompt=f"{original_prompt}\n用户最新调整：{diagnosis_feedback}",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == 6
    assert draft.build_constraints.get("requested_chapter_count") is None
    assert draft.build_constraints.get("chapter_count_source") != "user_request"
    assert "前置诊断选择" not in draft.user_prompt
    assert "第一章铺垫长度" not in draft.user_prompt


def test_normalize_planner_draft_preserves_llm_content_for_explicit_chapter_titles() -> None:
    payload = _planner_payload(chapter_count=2)
    payload.pop("course_name")
    payload["plan"] = "先理解函数的输入输出关系，再用一次函数图像建立斜率与截距的直观联系。"
    payload["chapters"] = [
        {
            "chapter_index": 1,
            "title": "函数概念与自变量取值",
            "objective": "理解函数关系并判断自变量取值范围。",
            "required_elements": ["函数关系", "自变量取值范围"],
            "writing_instructions": "用生活映射和反例解释函数关系。",
        },
        {
            "chapter_index": 2,
            "title": "一次函数图像与斜率截距",
            "objective": "把解析式参数与图像变化对应起来。",
            "required_elements": ["斜率的图像意义", "截距的图像意义"],
            "writing_instructions": "结合动态图示与典型例题讲解。",
        },
    ]

    draft = normalize_planner_draft(
        payload,
        course_id="course_titlefallback",
        user_prompt=(
            "我想学习初中函数，请构建一门 2 章课程："
            "第 1 章函数概念与自变量取值，第 2 章一次函数图像与斜率截距。"
            "每章要有清晰图示、例题、易错点和单元测试。"
        ),
        requested_digest_mode="sprint",
    )

    assert draft.course_name == "初中函数"
    assert [chapter.title for chapter in draft.chapters] == [
        "函数概念与自变量取值",
        "一次函数图像与斜率截距",
    ]
    assert len(draft.chapters) == 2
    assert draft.plan == payload["plan"]
    assert draft.chapters[0].objective == "理解函数关系并判断自变量取值范围。"
    assert draft.chapters[0].required_elements == ["函数关系", "自变量取值范围"]
    assert draft.chapters[1].writing_instructions == "结合动态图示与典型例题讲解。"
    required_text = "、".join(item for chapter in draft.chapters for item in chapter.required_elements)
    assert "核心概念" not in required_text
    assert "方法与典型题型" not in required_text
    assert "易错边界" not in required_text


def test_normalize_planner_draft_preserves_model_title_semantics() -> None:
    payload = _planner_payload(chapter_count=5)
    payload["chapters"] = [
        {
            "title": title,
            "objective": f"理解{title}。",
            "required_elements": elements,
            "writing_instructions": f"结合{title}的典型任务展开。",
        }
        for title, elements in [
            ("数与式：实数运算与代数式化简", ["实数运算", "代数式化简"]),
            ("方程与不等式：求解策略与应用建模", ["方程求解", "应用建模"]),
            ("函数：图像性质与解析式分析", ["函数图像", "解析式"]),
            ("几何：图形性质与逻辑证明技巧", ["图形性质", "几何证明"]),
            ("统计与概率：数据分析与模型应用", ["数据分析", "概率应用"]),
        ]
    ]

    draft = normalize_planner_draft(
        payload,
        course_id="初中数学",
        user_prompt="我想系统复习初中数学。",
        requested_digest_mode="sprint",
    )

    assert [chapter.title for chapter in draft.chapters] == [
        "数与式：实数运算与代数式化简",
        "方程与不等式：求解策略与应用建模",
        "函数：图像性质与解析式分析",
        "几何：图形性质与逻辑证明技巧",
        "统计与概率：数据分析与模型应用",
    ]


def test_normalize_planner_draft_respects_user_requested_chapter_range() -> None:
    payload = _planner_payload(chapter_count=9)

    draft = normalize_planner_draft(
        payload,
        course_id="高数",
        user_prompt="我要学习大学高等数学上册，请拆成 8-10 章，每章给出知识框架和练习。",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == 9
    assert draft.build_constraints["requested_chapter_min"] == 8
    assert draft.build_constraints["requested_chapter_max"] == 10
    assert draft.build_constraints["chapter_count_source"] == "user_request_range"
    assert not any("超出章节预算后合并覆盖" in item for item in draft.chapters[-1].required_elements)


def test_normalize_planner_draft_does_not_treat_duration_as_chapter_range() -> None:
    config = get_planner_mode_contract("sprint")

    draft = normalize_planner_draft(
        _planner_payload(chapter_count=config.max_chapters + 2),
        course_id="高数",
        user_prompt="我要学习大学高等数学上册，请构建一门 4 周系统课程。",
        requested_digest_mode="sprint",
    )

    assert len(draft.chapters) == config.max_chapters + 2
    assert draft.build_constraints.get("chapter_count_source") != "user_request_range"


def test_confirm_payload_rejects_excess_chapters_instead_of_merging_semantics() -> None:
    chapters = [
        {
            "title": f"章节 {index}",
            "objective": f"处理第 {index} 个学习任务",
            "required_elements": [f"任务 {index}", f"边界 {index}"],
        }
        for index in range(1, 6)
    ]

    with pytest.raises(ValueError, match="exceeds confirmed maximum 3"):
        _ensure_chapter_count_payload(
            chapters,
            min_chapters=2,
            max_chapters=3,
            digest_mode="systematic",
            user_prompt="测试章节压缩",
            plan={"course": "测试课程"},
        )


def test_confirm_payload_does_not_pad_missing_chapters_with_local_titles() -> None:
    shaped = _ensure_chapter_count_payload(
        [
            {
                "title": "矩阵",
                "objective": "讲清矩阵的基本概念。",
                "required_elements": ["矩阵定义", "矩阵运算"],
            }
        ],
        min_chapters=4,
        max_chapters=0,
        digest_mode="systematic",
        user_prompt="线性代数速成入门",
        plan={"course": "线性代数"},
    )

    assert len(shaped) == 1
    assert shaped[0]["title"] == "矩阵"


def test_planner_sse_preview_payload_exposes_new_planner_contract() -> None:
    preview = plan_draft_node._plan_preview_payload(
        {
            "course_id": "course_linear",
            "selected_file_ids": ["file_1"],
            "user_prompt": "线性代数速成入门",
            "digest_mode": "sprint",
            "planner_session_id": "session_1",
            "model_override": "reason",
            "planning_note": "用户要速成线性代数。",
            "material_note": "资料重点是矩阵和线性方程组。",
        },
        {
            "suggestion": "可以继续改成考试冲刺。",
            "plan": "按课程目录组织线性代数速成。",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "行列式",
                    "objective": "掌握行列式计算。",
                    "required_elements": ["行列式性质", "行列式展开"],
                }
            ],
        },
    )

    assert preview["course_id"] == "course_linear"
    assert preview["planner_session_id"] == "session_1"
    assert preview["chapters"][0]["title"] == "行列式"
    assert preview["plan"] == "按课程目录组织线性代数速成。"
    assert preview["suggestion"] == "可以继续改成考试冲刺。"
    assert preview["planning_note"] == "用户要速成线性代数。\n资料重点是矩阵和线性方程组。"


def test_parse_planner_response_reads_marker_protocol() -> None:
    parsed = plan_draft_node._parse_planner_response(
        f"""
{COURSE_NAME_START}初中数学复习{COURSE_NAME_END}
{PLAN_START}
先补数与式，再进入函数和几何，最后完成概率统计应用。
{PLAN_END}
{SUGGESTION_START}
如果更偏中考，可以增加压轴题比例。
{SUGGESTION_END}
{BUILD_CONSTRAINTS_START}
{{"chapter_length_profile":"detailed","chapter_min_words":3400,"chapter_target_words":4200,"chapter_max_words":5000}}
{BUILD_CONSTRAINTS_END}
{CHAPTERS_START}
[
  {{"title": "数与式基础", "objective": "掌握数式运算与基本变形。", "required_elements": ["实数与代数式", "方程基本变形"]}},
  {{"title": "函数图像", "objective": "理解函数图像与解析式的对应关系。", "required_elements": ["一次函数", "二次函数"]}}
]
{CHAPTERS_END}
"""
    )

    assert parsed["plan"].startswith("先补数与式")
    assert parsed["course_name"] == "初中数学复习"
    assert parsed["suggestion"].startswith("如果更偏中考")
    assert parsed["diagnose"] == []
    assert parsed["build_constraints"] == {
        "chapter_length_profile": "detailed",
        "chapter_min_words": 3400,
        "chapter_target_words": 4200,
        "chapter_max_words": 5000,
    }
    assert parsed["chapters"][0]["title"] == "数与式基础"
    assert parsed["chapters"][0]["required_elements"] == ["实数与代数式", "方程基本变形"]
    assert "writing_instructions" not in parsed["chapters"][0]


def test_parse_diagnosis_response_reads_four_choice_questions() -> None:
    parsed = plan_draft_node._parse_diagnosis_response(
        f"""
{DIAGNOSE_START}
[
  {{"question":"极限基础从哪一层起？","purpose":"文档落点：调整极限定义铺垫。","options":["先补函数概念｜每章先解释前置函数语言","从极限直觉起｜先用图像与趋势建立直觉","直接讲定义｜压缩铺垫并展开严格定义","从典型题查漏｜用题型暴露基础缺口"]}},
  {{"question":"高数讲解先重哪块？","purpose":"文档落点：调整正文篇幅。","options":["极限定义｜增加定义与边界辨析篇幅","导数应用｜增加变化率和应用例题","积分计算｜增加计算方法与变式训练","综合串联｜均衡分配并强化跨章联系"]}},
  {{"question":"每节练习怎么配置？","purpose":"文档落点：调整练习密度。","options":["随堂一题｜每节只保留一题即时检查","典型题组｜每个方法安排成组例题","增加变式｜每个核心题追加条件变化","章末小测｜减少随堂题并集中章末检测"]}},
  {{"question":"错题解析需要多细？","purpose":"文档落点：调整答案解析。","options":["只给要点｜答案保留关键结论和抓手","分步依据｜解析逐步写出判断依据","重点错因｜答案增加错误路径对照","补充变式｜解析后追加同考点变式"]}}
]
{DIAGNOSE_END}
"""
    )

    assert len(parsed) == 4
    assert parsed[0]["question"] == "极限基础从哪一层起？"
    assert parsed[1]["options"][0] == "极限定义｜增加定义与边界辨析篇幅"


def test_parse_generated_course_name_reads_short_title() -> None:
    parsed = plan_draft_node._parse_generated_course_name(
        f"{COURSE_NAME_START}高等数学期末冲刺{COURSE_NAME_END}"
    )

    assert parsed == "高等数学期末冲刺"


def test_generated_course_name_is_not_overwritten_by_regex_guess() -> None:
    resolved = _resolve_effective_course_name(
        raw_draft={"course_name": "青少年人工智能素养"},
        generated_course_name="青少年人工智能素养",
        request_prompt="请设计一个面向初中生的课程，帮助他们理解人工智能、数据偏见和隐私保护。",
    )

    assert resolved == "青少年人工智能素养"


def test_course_name_request_parser_is_only_used_when_model_name_is_missing() -> None:
    resolved = _resolve_effective_course_name(
        raw_draft={},
        generated_course_name="",
        request_prompt="我想构建一门大学高数期末复习课，覆盖极限、导数和积分。",
    )

    assert resolved == "大学高数期末复习"


def test_normalize_planner_diagnosis_draft_preserves_llm_question_wording() -> None:
    normalized = normalize_planner_diagnosis_draft(
        {
            "diagnose": [
                {
                    "question": "图示辅助的重点？",
                    "purpose": "影响图示重点。",
                    "options": [
                        "图示辅助",
                        "图示重点",
                        "多用图示",
                        "少用图示",
                    ],
                    "answer": "图示辅助",
                },
                {"question": "", "purpose": "空问题应该丢弃。", "options": ["概念", "练习"]},
            ],
            "diagnose_status": "unknown",
        },
        course_id="初中函数",
        user_prompt="14 天复习函数、几何和统计",
        requested_digest_mode="sprint",
    )

    diagnose = normalized["diagnose"]
    assert normalized["planner_stage"] == "diagnosis"
    assert normalized["diagnose_status"] == "pending"
    assert len(diagnose) == 1
    assert diagnose[0]["question"] == "图示辅助的重点？"
    assert diagnose[0]["answer"] == "图示辅助"
    assert diagnose[0]["answer"] in diagnose[0]["options"]
    assert all(item["question"] for item in diagnose)
    assert all(len(item["options"]) == 4 for item in diagnose)
    assert all(len(set(item["options"])) == 4 for item in diagnose)
    assert all(len(option) <= 16 for item in diagnose for option in item["options"])
    assert "当前基础怎样？" not in {item["question"] for item in diagnose}


def test_normalize_planner_diagnosis_draft_skips_empty_model_questions() -> None:
    normalized = normalize_planner_diagnosis_draft(
        {
            "diagnose": [
                {
                    "question": "练习怎么配？",
                    "purpose": "影响练习密度。",
                    "options": ["少练", "多练"],
                },
            ],
        },
        course_id="初中函数",
        user_prompt="14 天复习函数、几何和统计",
        requested_digest_mode="sprint",
    )

    assert normalized["diagnose"] == []
    assert normalized["diagnose_status"] == "skipped"


def test_normalize_planner_diagnosis_draft_clears_previous_resolution_for_new_questions() -> None:
    normalized = normalize_planner_diagnosis_draft(
        {
            "diagnose": [
                {
                    "question": "行列式的几何意义掌握得怎样？",
                    "purpose": "调整行列式章节的讲解深度。",
                    "options": ["完全不了解", "只会计算", "理解面积", "能够推广"],
                },
            ],
            "diagnose_status": "pending",
        },
        course_id="线性代数",
        user_prompt="复习矩阵乘法与行列式",
        requested_digest_mode="systematic",
        latest_plan={
            "planning_note": "学习目标：复习矩阵乘法与行列式。。规划节奏：紧凑冲刺。",
            "diagnose": [
                {
                    "question": "矩阵乘法掌握得怎样？",
                    "purpose": "调整矩阵章节的讲解深度。",
                    "options": ["完全不了解", "只会公式", "理解规则", "能够应用"],
                    "answer": "理解规则",
                },
            ],
            "diagnose_status": "answered",
            "diagnose_note": "使用标准讲解与基础练习，两章均衡。",
        },
    )

    assert normalized["diagnose_status"] == "pending"
    assert normalized["diagnose_note"] == ""
    assert normalized["planning_note"] == "学习目标：复习矩阵乘法与行列式。规划节奏：紧凑冲刺。"
    assert normalized["diagnose"][0]["question"] == "行列式的几何意义掌握得怎样？"
    assert normalized["diagnose"][0]["answer"] == ""


def test_refresh_diagnosis_preserves_previous_formal_plan() -> None:
    latest_plan = _planner_payload(chapter_count=2)
    latest_plan["build_constraints"] = {
        "chapter_length_profile": "detailed",
        "chapter_min_words": 3400,
        "chapter_target_words": 4200,
        "chapter_max_words": 5000,
    }

    normalized = normalize_planner_diagnosis_draft(
        {
            "diagnose": [
                {
                    "question": "这轮复习最需要加强哪类训练？",
                    "purpose": "文档落点：调整例题和练习密度。",
                    "options": ["概念辨析", "步骤计算", "综合应用", "错因复盘"],
                }
            ],
            "diagnose_status": "pending",
        },
        course_id="高等数学",
        user_prompt="保持两章结构和知识点边界不变，同时重新生成前置诊断。",
        requested_digest_mode="systematic",
        latest_plan=latest_plan,
    )

    assert normalized["suggestion"] == latest_plan["suggestion"]
    assert normalized["plan"] == latest_plan["plan"]
    assert normalized["chapters"] == latest_plan["chapters"]
    assert normalized["build_constraints"] == latest_plan["build_constraints"]
    assert normalized["diagnose_status"] == "pending"
    assert normalized["diagnose"][0]["question"] == "这轮复习最需要加强哪类训练？"


def test_normalize_planner_draft_rejects_locked_knowledge_boundary_changes() -> None:
    previous = _planner_payload(chapter_count=2)
    current = _planner_payload(chapter_count=2)
    current["chapters"][0]["required_elements"] = ["切片 1 的学习任务"]

    with pytest.raises(ValueError, match="locked required_elements"):
        normalize_planner_draft(
            current,
            course_id="高等数学",
            user_prompt="系统复习高等数学",
            requested_digest_mode="systematic",
            latest_plan=previous,
            revision_feedback="保持两章结构和知识点边界不变。",
        )


def test_normalize_planner_draft_allows_explicit_scope_change_without_lock() -> None:
    previous = _planner_payload(chapter_count=2)
    current = _planner_payload(chapter_count=2)
    current["chapters"][0]["required_elements"] = ["切片 1 的学习任务"]

    draft = normalize_planner_draft(
        current,
        course_id="高等数学",
        user_prompt="系统复习高等数学",
        requested_digest_mode="systematic",
        latest_plan=previous,
        revision_feedback="删除第一章的边界辨析知识点。",
    )

    assert draft.chapters[0].required_elements == ["切片 1 的学习任务"]


def test_partial_chapters_supports_streaming_preview() -> None:
    chapters = plan_draft_node._partial_chapters(
        f'{CHAPTERS_START}[{{"title":"数与式","objective":"掌握代数式与方程变形。","required_elements":["代数式","方程"]}},{{"title":"函数图像","objective":"理解一次函数图像。","required_elements":["一次函数"'
    )

    assert [chapter["title"] for chapter in chapters] == ["数与式"]
    assert chapters[0]["required_elements"] == ["代数式", "方程"]
    assert chapters[0]["objective"] == "掌握代数式与方程变形。"


def test_parse_planner_response_rejects_empty_chapter_requirements() -> None:
    with pytest.raises(ValueError, match="required_elements"):
        plan_draft_node._parse_planner_response(
            f"""
{COURSE_NAME_START}计算基础{COURSE_NAME_END}
{PLAN_START}一段方案。{PLAN_END}
{SUGGESTION_START}一段建议。{SUGGESTION_END}
{CHAPTERS_START}[{{"title": "计算基础", "objective": "掌握基础计算。", "required_elements": []}}]{CHAPTERS_END}
"""
        )


def test_planner_node_create_generates_diagnosis_before_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted_tokens: list[str] = []
    emitted_events: list[tuple[str, dict | None]] = []
    raw_output = (
        f"{COURSE_NAME_START}三年级数学巩固{COURSE_NAME_END}"
        f"{DIAGNOSE_START}"
        '[{"question":"乘除法哪里最容易错？","purpose":"文档落点：调整计算基础铺垫。",'
        '"options":["口诀不熟｜增加口算与口诀回顾","顺序混淆｜增加运算顺序辨析","竖式易错｜增加竖式步骤与检查","应用题转换｜增加情境到算式的转换"]},'
        '{"question":"三年级数学先讲哪块？","purpose":"文档落点：调整正文篇幅。",'
        '"options":["乘除法｜增加计算方法与练习","长度单位｜增加换算与测量任务","几何图形｜增加识图和性质辨析","应用题｜增加建模与列式训练"]},'
        '{"question":"每节练习怎么配置？","purpose":"文档落点：调整练习密度。",'
        '"options":["随堂一题｜每节保留一题即时检查","典型题组｜每个方法安排成组练习","增加变式｜核心题追加条件变化","章末小测｜减少随堂题并集中检测"]},'
        '{"question":"应用题解析写多细？","purpose":"文档落点：调整答案解析。",'
        '"options":["只给要点｜答案保留关键结论","分步列式｜逐步解释条件到算式","解释错因｜增加错误路径对照","补充变式｜解析后追加同类变式"]}]'
        f"{DIAGNOSE_END}"
    )

    def fake_acompletion_stream(*args, **kwargs) -> Iterator[str]:
        del args
        attempt_callback = kwargs.pop("attempt_callback")
        assert callable(attempt_callback)

        async def _gen():
            await attempt_callback(
                "fallback",
                {"attempt": 1, "endpoint_role": "fallback", "error_type": "APIConnectionError"},
            )
            yield raw_output

        return _gen()

    async def fake_emit_token(state, token: str) -> None:
        del state
        emitted_tokens.append(token)

    async def fake_emit_event(state, *, event: str, detail: str, payload=None) -> None:
        del state, detail
        emitted_events.append((event, payload))

    monkeypatch.setattr(plan_draft_node, "acompletion_stream", fake_acompletion_stream)
    monkeypatch.setattr(plan_draft_node, "emit_planner_token", fake_emit_token)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "planner_operation": "create",
                "material_context": _material_context(),
                "planning_note": "用户希望整理三年级数学。",
                "material_note": "没有绑定上传资料，只能按目标规划。",
                "user_prompt": "三年级数学",
                "digest_mode": "sprint",
                "message_history": ["用户：三年级数学"],
            }
        )
    )

    assert "".join(emitted_tokens) == (
        "正在为「三年级数学巩固」准备前置诊断\n\n"
        "1. 乘除法哪里最容易错？\n"
        "2. 三年级数学先讲哪块？\n"
        "3. 每节练习怎么配置？\n"
        "4. 应用题解析写多细？"
    )
    assert result["build_plan_draft"]["planner_stage"] == "diagnosis"
    assert result["build_plan_draft"]["plan"] == ""
    assert result["build_plan_draft"]["chapters"] == []
    assert result["build_plan_draft"]["diagnose_status"] == "pending"
    assert result["build_plan_draft"]["course_name"] == "三年级数学巩固"
    assert result["generated_course_name"] == "三年级数学巩固"
    assert result["build_plan_draft"]["diagnose"][0]["question"] == "乘除法哪里最容易错？"
    assert result["build_plan_draft"]["diagnose"][0]["options"] == [
        "口诀不熟｜增加口算与口诀回顾",
        "顺序混淆｜增加运算顺序辨析",
        "竖式易错｜增加竖式步骤与检查",
        "应用题转换｜增加情境到算式的转换",
    ]
    assert [event for event, _payload in emitted_events] == [
        "planner.diagnose.started",
        "planner.llm.fallback",
        "planner.diagnose.ready",
    ]
    assert emitted_events[-1][1]["plan_preview"]["diagnose_status"] == "pending"


def test_planner_node_streams_plan_and_builds_new_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted_tokens: list[str] = []
    emitted_events: list[tuple[str, dict | None]] = []
    raw_output = (
        f"{COURSE_NAME_START}三年级数学{COURSE_NAME_END}"
        f"{PLAN_START}本轮先识别目标，再组织章节和练习。{PLAN_END}"
        f"{SUGGESTION_START}可以继续改成考试冲刺。{SUGGESTION_END}"
        f'{CHAPTERS_START}[{{"title":"目标拆解","objective":"明确学习范围与练习边界。","required_elements":["学习范围","练习边界"]}}]{CHAPTERS_END}'
    )

    def fake_acompletion_stream(*args, **kwargs) -> Iterator[str]:
        del args, kwargs

        async def _gen():
            yield raw_output

        return _gen()

    async def fake_emit_token(state, token: str) -> None:
        del state
        emitted_tokens.append(token)

    async def fake_emit_event(state, *, event: str, detail: str, payload=None) -> None:
        del state, detail
        emitted_events.append((event, payload))

    monkeypatch.setattr(plan_draft_node, "acompletion_stream", fake_acompletion_stream)
    monkeypatch.setattr(plan_draft_node, "emit_planner_token", fake_emit_token)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "material_context": _material_context(),
                "planning_note": "用户希望整理三年级数学。",
                "material_note": "没有绑定上传资料，只能按目标规划。",
                "user_prompt": "三年级数学",
                "digest_mode": "sprint",
                "message_history": ["用户：三年级数学"],
            }
        )
    )

    assert "".join(emitted_tokens) == "\n\n本轮先识别目标，再组织章节和练习。"
    assert result["build_plan_draft"]["plan"] == "本轮先识别目标，再组织章节和练习。"
    assert result["build_plan_draft"]["suggestion"] == "可以继续改成考试冲刺。"
    assert result["build_plan_draft"]["chapters"][0]["title"] == "目标拆解"
    assert [event for event, _payload in emitted_events] == [
        "planner.plan.started",
        "planner.suggestion.started",
        "planner.chapters.started",
        "planner.chapters.progress",
        "planner.plan.ready",
    ]
    progress_payload = emitted_events[3][1]
    assert progress_payload is not None
    assert progress_payload["partial_chapter_count"] == 1
    assert progress_payload["plan_preview"]["plan"] == "本轮先识别目标，再组织章节和练习。"
    assert progress_payload["plan_preview"]["chapters"][0]["title"] == "目标拆解"


def test_planner_node_uses_llm_repair_instead_of_local_content_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_output = (
        f"{COURSE_NAME_START}初中函数{COURSE_NAME_END}"
        f"{PLAN_START}模型第一次误拆成三章。{PLAN_END}"
        f"{SUGGESTION_START}保持两章要求。{SUGGESTION_END}"
        f'{CHAPTERS_START}['
        '{"title":"函数概念","objective":"理解函数关系。","required_elements":["函数关系"]},'
        '{"title":"一次函数","objective":"理解斜率与截距。","required_elements":["斜率与截距"]},'
        '{"title":"额外训练","objective":"完成综合练习。","required_elements":["综合练习"]}'
        f']{CHAPTERS_END}'
    )
    repaired_output = (
        f"{COURSE_NAME_START}初中函数{COURSE_NAME_END}"
        f"{PLAN_START}先建立函数关系，再把参数变化与一次函数图像对应起来。{PLAN_END}"
        f"{SUGGESTION_START}可继续调整图示和练习密度。{SUGGESTION_END}"
        f'{CHAPTERS_START}['
        '{"title":"函数概念与自变量","objective":"理解函数关系并判断自变量范围。","required_elements":["函数关系","自变量取值范围"]},'
        '{"title":"一次函数图像","objective":"把斜率截距与图像变化对应起来。","required_elements":["斜率的图像意义","截距的图像意义"]}'
        f']{CHAPTERS_END}'
    )
    emitted_events: list[str] = []

    async def fake_stream(state, **kwargs):
        del state, kwargs
        return invalid_output

    async def fake_repair(messages, **kwargs):
        del kwargs
        assert "does not match requested 2" in messages[-1]["content"]
        return repaired_output

    async def fake_emit_event(state, *, event: str, detail: str, payload=None) -> None:
        del state, detail, payload
        emitted_events.append(event)

    monkeypatch.setattr(plan_draft_node, "_stream_planner_response", fake_stream)
    monkeypatch.setattr(plan_draft_node, "acompletion_with_fallback", fake_repair)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "planner_operation": "append",
                "material_context": _material_context(),
                "planning_note": "生成两章初中函数课程。",
                "material_note": "没有上传资料。",
                "user_prompt": "请构建两章初中函数课程。",
                "feedback_message": "严格只生成 2 章。",
                "digest_mode": "sprint",
                "message_history": [],
                "latest_plan": {"course_name": "初中函数", "course_icon": "function"},
            }
        )
    )

    assert result["build_plan_draft"]["plan"] == "先建立函数关系，再把参数变化与一次函数图像对应起来。"
    assert [chapter["title"] for chapter in result["build_plan_draft"]["chapters"]] == [
        "函数概念与自变量",
        "一次函数图像",
    ]
    assert "planner.plan.repairing" in emitted_events


def test_planner_node_repairs_locked_knowledge_boundary_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _planner_payload(chapter_count=2)
    invalid_output = (
        f"{COURSE_NAME_START}高数主线重建{COURSE_NAME_END}"
        f"{PLAN_START}保持两章复习路径。{PLAN_END}"
        f"{SUGGESTION_START}只调整讲解深度。{SUGGESTION_END}"
        f'{CHAPTERS_START}['
        '{"title":"任务切片 1","objective":"理解并完成切片 1 的学习任务。",'
        '"required_elements":["切片 1 的学习任务"]},'
        '{"title":"任务切片 2","objective":"理解并完成切片 2 的学习任务。",'
        '"required_elements":["切片 2 的学习任务","切片 2 的边界"]}'
        f']{CHAPTERS_END}'
    )
    repaired_output = (
        f"{COURSE_NAME_START}高数主线重建{COURSE_NAME_END}"
        f"{PLAN_START}保持两章复习路径，只调整讲解深度。{PLAN_END}"
        f"{SUGGESTION_START}可以继续调整例题密度。{SUGGESTION_END}"
        f'{CHAPTERS_START}['
        '{"title":"任务切片 1","objective":"理解并完成切片 1 的学习任务。",'
        '"required_elements":["切片 1 的学习任务","切片 1 的边界"]},'
        '{"title":"任务切片 2","objective":"理解并完成切片 2 的学习任务。",'
        '"required_elements":["切片 2 的学习任务","切片 2 的边界"]}'
        f']{CHAPTERS_END}'
    )
    emitted_events: list[str] = []

    async def fake_stream(state, **kwargs):
        del state, kwargs
        return invalid_output

    async def fake_repair(messages, **kwargs):
        del kwargs
        prompt_text = "\n".join(message["content"] for message in messages)
        assert "required_elements 必须逐章原样输出" in prompt_text
        assert "locked required_elements" in messages[-1]["content"]
        return repaired_output

    async def fake_emit_event(state, *, event: str, detail: str, payload=None) -> None:
        del state, detail, payload
        emitted_events.append(event)

    monkeypatch.setattr(plan_draft_node, "_stream_planner_response", fake_stream)
    monkeypatch.setattr(plan_draft_node, "acompletion_with_fallback", fake_repair)
    monkeypatch.setattr(plan_draft_node, "emit_planner_event", fake_emit_event)

    node = plan_draft_node.build_compose_planner_draft_node(context=object())
    result = asyncio.run(
        node(
            {
                "course_id": "course_test",
                "planner_session_id": "session_test",
                "planner_operation": "append",
                "material_context": _material_context(),
                "planning_note": "保持原有学习范围。",
                "material_note": "没有上传资料。",
                "user_prompt": "系统复习高等数学",
                "feedback_message": "前置诊断选择：问题：讲解深度；回答：细致推导",
                "digest_mode": "systematic",
                "message_history": [
                    "用户: 保持两章结构和知识点边界不变，同时重新生成前置诊断。",
                    "规划器: 请先完成新的前置诊断。",
                    "用户: 前置诊断选择：问题：讲解深度；回答：细致推导",
                ],
                "latest_plan": previous,
            }
        )
    )

    assert [chapter["title"] for chapter in result["build_plan_draft"]["chapters"]] == [
        chapter["title"] for chapter in previous["chapters"]
    ]
    assert [chapter["required_elements"] for chapter in result["build_plan_draft"]["chapters"]] == [
        chapter["required_elements"] for chapter in previous["chapters"]
    ]
    assert "planner.plan.repairing" in emitted_events
