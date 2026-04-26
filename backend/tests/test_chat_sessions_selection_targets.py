import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import ChatSession, Subject
from app.repositories.chats_repo import create_chat_session, create_message_pair
from app.schemas.chats import ChatSelectionContext
from app.shared.infra.strategies import StrategyMode
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.lib import sessioning
from app.workflows.interact.chat.lib.execution import InteractExecutionMode, select_execution_mode
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RetrievedContext,
    SubjectContextSummary,
    WeakPointSummary,
)
from app.workflows.interact.chat.nodes import session as session_nodes
from app.workflows.interact.chat.prompts import build_chat_messages
from app.workflows.interact.chat import use_cases
from app.workflows.interact.chat.use_cases import list_chat_sessions, list_recent_chat_sessions


def anyio_backend() -> str:
    return "asyncio"


def test_list_chat_sessions_includes_latest_doc_selection_target():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        normal = create_chat_session(
            session,
            subject="demo",
            user_id="user-1",
            title="普通对话",
        )
        quick = create_chat_session(
            session,
            subject="demo",
            user_id="user-1",
            title="划词对话",
            source="quick_chat",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=quick.id,
            user_content="旧问题",
            assistant_content="旧回答",
            source="quick_chat",
            anchor_id="old-anchor",
            selected_text="旧划词",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=quick.id,
            user_content="新问题",
            assistant_content="新回答",
            source="quick_chat",
            anchor_id="new-anchor",
            selected_text="新划词",
        )
        create_message_pair(
            session,
            subject="demo",
            user_id="user-1",
            session_id=normal.id,
            user_content="普通问题",
            assistant_content="普通回答",
        )

        page = list_chat_sessions(
            session,
            subject="demo",
            user_id="user-1",
            page=1,
            size=10,
        )

    items = {item.id: item for item in page.items}
    assert items[quick.id].anchor_id == "new-anchor"
    assert items[quick.id].selected_text == "新划词"
    assert items[normal.id].anchor_id is None
    assert items[normal.id].selected_text is None


def test_list_recent_chat_sessions_includes_subject_metadata_across_subjects():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Subject(user_id="user-1", slug="math", name="数学"))
        session.add(Subject(user_id="user-1", slug="physics", name="物理"))
        session.commit()

        math = create_chat_session(
            session,
            subject="math",
            user_id="user-1",
            title="数学对话",
        )
        physics = create_chat_session(
            session,
            subject="physics",
            user_id="user-1",
            title="物理对话",
        )
        other_user = create_chat_session(
            session,
            subject="math",
            user_id="user-2",
            title="别人的对话",
        )
        create_message_pair(
            session,
            subject="math",
            user_id="user-1",
            session_id=math.id,
            user_content="数学问题",
            assistant_content="数学回答",
        )
        create_message_pair(
            session,
            subject="physics",
            user_id="user-1",
            session_id=physics.id,
            user_content="物理问题",
            assistant_content="物理回答",
            source="quick_chat",
            anchor_id="force",
            selected_text="力是物体间的相互作用。",
        )
        create_message_pair(
            session,
            subject="math",
            user_id="user-2",
            session_id=other_user.id,
            user_content="别人的问题",
            assistant_content="别人的回答",
        )

        page = list_recent_chat_sessions(
            session,
            user_id="user-1",
            page=1,
            size=10,
        )

    items = {item.id: item for item in page.items}
    assert set(items) == {math.id, physics.id}
    assert items[math.id].subject_id == "math"
    assert items[math.id].subject_name == "数学"
    assert items[physics.id].subject_id == "physics"
    assert items[physics.id].subject_name == "物理"
    assert items[physics.id].anchor_id == "force"
    assert items[physics.id].selected_text == "力是物体间的相互作用。"


def test_selection_prompt_keeps_recent_mistakes_as_secondary_context():
    messages = build_chat_messages(
        subject="英语",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[
            MistakeSummary(
                question_stem="在图书馆借书的对话体现了哪三个核心要素？",
                user_answer="",
                correct_answer="心理动因、语言表达、情境反馈。",
                analysis="Possible error cause: knowledge_gap",
            )
        ],
        question="看不懂这个",
        source="quick_chat",
        selected_context=None,
        selection_context=ChatSelectionContext(
            selected_text="含具体时间点（yesterday, last week）→ 用一般过去时。",
            section_title="一般过去时 vs. 现在完成时",
            section_excerpt="含时间段（since, for）→ 用现在完成时。",
        ),
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "文档划词问答私教" in system_prompt
    assert "用户入口上下文（本轮主证据）" in system_prompt
    assert "近期错题只用于调整讲解深浅" in system_prompt
    assert system_prompt.index("用户入口上下文（本轮主证据）") < system_prompt.index("近期错题：")
    assert "含具体时间点" in system_prompt
    assert "在图书馆借书" not in system_prompt


def test_selection_prompt_omits_low_relevance_retrieval_context_when_selection_is_primary():
    repeated_content = (
        "# 基础句型与日常表达\n\n"
        "## 一、核心问候语\n\n"
        "Halo 是全天通用问候语。\n\n"
        "## 二、自我介绍五要素\n\n"
        "姓名：Nama saya Li Wei.\n"
        "来源：Saya dari Beijing.\n"
        "年龄：Saya berusia 20 tahun.\n"
        "身份：Saya siswa di universitas.\n"
        "住址：Saya tinggal di kampus.\n"
    )
    retrieval_results = [
        RetrievedContext(
            chunk_id=0,
            document_id=0,
            title="一、核心问候语",
            header_path="一、核心问候语",
            content=repeated_content,
            score=0.23,
            low_relevance=True,
            retrieval_source="knowledge_unit",
        ),
        RetrievedContext(
            chunk_id=0,
            document_id=0,
            title="五、句子结构训练",
            header_path="五、句子结构训练",
            content=repeated_content,
            score=0.23,
            low_relevance=True,
            retrieval_source="knowledge_unit",
        ),
    ]

    messages = build_chat_messages(
        subject="印尼语",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=retrieval_results,
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question="这些有什么规律吗",
        source="quick_chat",
        selected_context=None,
        selection_context=ChatSelectionContext(
            selected_text="姓名：Nama saya Li Wei.\n来源：Saya dari Beijing.",
            section_title="二、自我介绍五要素",
        ),
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "[资料:knowledge_unit]" not in system_prompt
    assert system_prompt.count("Halo 是全天通用问候语") == 0


def test_selection_prompt_skips_redundant_retrieval_when_primary_context_is_enough():
    section_excerpt = (
        "时间主题：线性不可逆的集体焦虑。"
        "Time and tide wait for no man 强调时间不可逆，也反映工业化社会对效率、计划和准时的重视。"
        "它不是单纯催促人快一点，而是在提醒个体需要提前判断后果并主动行动。"
        "在非线性时间文化中，这句话可能被误解为冷漠或功利，但核心其实是提前干预比事后补救更有效。"
        "这段内容已经足够作为划词问答的主证据，不需要再把同一个知识单元作为参考资料重复塞入模型输入。"
    )
    messages = build_chat_messages(
        subject="英语谚语",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=[
            RetrievedContext(
                chunk_id=1,
                document_id=1,
                title="时间主题：线性不可逆的集体焦虑",
                header_path="英语谚语 > 时间主题",
                content=section_excerpt,
                score=1.0,
                low_relevance=False,
                retrieval_source="knowledge_unit",
            )
        ],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question="看不懂",
        source="quick_chat",
        selected_context=None,
        selection_context=ChatSelectionContext(
            selected_text="Time and tide wait for no man 强调时间不可逆。",
            heading_path=["英语谚语", "时间主题"],
            before_text=section_excerpt,
            after_text=section_excerpt,
        ),
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "用户入口上下文（本轮主证据）" in system_prompt
    assert "参考资料：" not in system_prompt
    assert "[资料:knowledge_unit]" not in system_prompt


def test_selection_prompt_prioritizes_relevant_weak_points():
    messages = build_chat_messages(
        subject="英语",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[
            WeakPointSummary(knowledge_point="实践方法：", mastery_text="0%"),
            WeakPointSummary(knowledge_point="常用问候语", mastery_text="0%"),
            WeakPointSummary(knowledge_point="第三人称单数规则", mastery_text="0%"),
        ],
        recent_mistakes=[],
        question="这里说goes不能写成goes是啥意思",
        source="quick_chat",
        selected_context=None,
        selection_context=ChatSelectionContext(
            selected_text="重点：避免漏写 -es，如 goes 不能写成 goes（拼写错误常见于笔误）",
            section_title="第三人称单数规则",
        ),
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "第三人称单数规则（掌握度：0%）" in system_prompt
    assert "常用问候语（掌握度：0%）" not in system_prompt


def test_prompt_uses_subject_display_name_and_background():
    messages = build_chat_messages(
        subject="subj_okl1hpt8kwef",
        strategy_mode=StrategyMode.GUIDED,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question="这里是什么意思",
        subject_context=SubjectContextSummary(
            subject_id="subj_okl1hpt8kwef",
            subject_name="基础印尼语",
            description="问候语、自我介绍和简单时态。",
            learning_intent="掌握日常交流的基础句型。",
            discipline="语言学习",
            avg_mastery=0.34,
            weak_knowledge_unit_count=6,
            pending_review_count=2,
            due_review_count=1,
            difficulty_focus="easy",
        ),
        source="quick_chat",
        selected_context=None,
        selection_context=ChatSelectionContext(
            selected_text="Nama saya Li Wei.",
            section_title="自我介绍",
        ),
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "文档划词问答私教" in system_prompt
    assert "「基础印尼语」" in system_prompt
    assert "「subj_okl1hpt8kwef」" not in system_prompt
    assert "本轮以用户入口上下文为主" in system_prompt
    assert "学科说明：问候语、自我介绍和简单时态。" not in system_prompt
    assert "用户整体画像：平均掌握度 34%" in system_prompt


def test_regular_chitchat_prompt_does_not_force_subject_context():
    messages = build_chat_messages(
        subject="subj_6k6j1yrmzo5a",
        strategy_mode=StrategyMode.EXPLAIN,
        retrieval_results=[
            RetrievedContext(
                chunk_id=1,
                document_id=1,
                title="英语谚语",
                header_path="英语谚语 > 文化隐喻",
                content="Every cloud has a silver lining 用来表达逆境中也有希望。",
                score=0.92,
                low_relevance=False,
                retrieval_source="knowledge_unit",
            )
        ],
        recent_messages=[],
        weak_points=[WeakPointSummary(knowledge_point="谚语应用", mastery_text="20%")],
        recent_mistakes=[
            MistakeSummary(
                question_stem="Every cloud has a silver lining 适合什么场景？",
                user_answer="",
                correct_answer="安慰别人或表达乐观。",
                analysis="knowledge_gap",
            )
        ],
        question="好无聊",
        subject_context=SubjectContextSummary(
            subject_id="subj_6k6j1yrmzo5a",
            subject_name="学谚语用起来",
            description="围绕英语谚语的主题簇与文化语境展开。",
            user_intent="系统学习英语谚语。",
            learning_intent="建立语言文化理解与实际应用能力。",
            subject_intro="当前知识文档重点覆盖按主题分类英语谚语。",
        ),
        source=None,
        selected_context=None,
        selection_context=None,
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "通用对话伙伴" in system_prompt
    assert "通用对话：当前没有用户入口上下文" in system_prompt
    assert "通用对话模式：先回应用户当下感受" in system_prompt
    assert "讲解模式：先定义核心概念" not in system_prompt
    assert "当前学习空间：学谚语用起来" in system_prompt
    assert "学科说明：围绕英语谚语" not in system_prompt
    assert "用户建课意图：系统学习英语谚语" not in system_prompt
    assert "谚语应用（掌握度" not in system_prompt
    assert "Every cloud has a silver lining" not in system_prompt


def test_regular_learning_prompt_keeps_subject_context_when_requested():
    messages = build_chat_messages(
        subject="subj_6k6j1yrmzo5a",
        strategy_mode=StrategyMode.PLANNING,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question="这门课怎么学比较好？",
        subject_context=SubjectContextSummary(
            subject_id="subj_6k6j1yrmzo5a",
            subject_name="学谚语用起来",
            description="围绕英语谚语的主题簇与文化语境展开。",
            user_intent="系统学习英语谚语。",
            learning_intent="建立语言文化理解与实际应用能力。",
        ),
        source=None,
        selected_context=None,
        selection_context=None,
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "常规学习对话" in system_prompt
    assert "常规学习对话：可以使用当前学习空间背景" in system_prompt
    assert "学科说明：围绕英语谚语" in system_prompt
    assert "用户建课意图：系统学习英语谚语" in system_prompt


def test_exam_question_prompt_uses_dedicated_template():
    messages = build_chat_messages(
        subject="数学",
        strategy_mode=StrategyMode.REVIEW,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[WeakPointSummary(knowledge_point="一元二次方程", mastery_text="40%")],
        recent_mistakes=[],
        question="为什么这题错了？",
        subject_context=SubjectContextSummary(
            subject_id="math",
            subject_name="数学",
            description="初中数学。",
        ),
        source="exam_question",
        selected_context="题干：求方程 x^2 - 5x + 6 = 0 的解。\n用户答案：x=1,6\n参考答案：x=2,3",
        selection_context=None,
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "考试题讲解私教" in system_prompt
    assert "题目入口上下文（本轮主证据）" in system_prompt
    assert "这题 / 这个 / 这里 / 为什么错 / 答案" in system_prompt
    assert "文档划词问答私教" not in system_prompt


def test_build_assistant_prompt_uses_dedicated_template():
    messages = build_chat_messages(
        subject="英语谚语",
        strategy_mode=StrategyMode.EXPLAIN,
        retrieval_results=[],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question="为什么还没生成完？",
        subject_context=SubjectContextSummary(
            subject_id="proverbs",
            subject_name="英语谚语",
            description="按主题组织英语谚语。",
        ),
        source="build_assistant",
        selected_context="当前阶段：docgen_chapter_enhancement；已生成 3/5 章。",
        selection_context=None,
        source_chunk_id=None,
    )

    system_prompt = messages[0]["content"]
    assert "知识库构建助手" in system_prompt
    assert "构建入口上下文（本轮主证据）" in system_prompt
    assert "不要把构建过程问题误当成普通学科讲课" in system_prompt
    assert "考试题讲解私教" not in system_prompt


def test_general_chat_does_not_enable_subject_tool_mode_for_generic_planning():
    execution_mode = select_execution_mode(
        question="帮我计划一下今晚吃什么",
        selected_context=None,
        strategy_mode=StrategyMode.PLANNING,
        retrieval_results=[],
        allow_subject_tools=False,
    )

    assert execution_mode == InteractExecutionMode.SINGLE_PASS


@pytest.mark.anyio
async def test_chat_workflow_session_nodes_create_and_finalize_session(monkeypatch):
    async def fake_title(**_kwargs):
        return "完成时辨析"

    monkeypatch.setattr(session_nodes, "generate_session_title", fake_title)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        context = WorkflowContext(workflow_name="interact.chat", subject="demo")
        resolve_node = session_nodes.build_resolve_chat_session_node(
            context=context,
            session=session,
        )
        state = await resolve_node(
            {
                "subject": "demo",
                "user_id": "user-1",
                "session_id": None,
                "question": "看不懂这个",
                "source": "quick_chat",
                "stream_interrupted": False,
                "error": None,
            }
        )

        created = session.get(ChatSession, state["session_id"])
        assert created is not None
        assert created.source == "quick_chat"
        assert state["session_created"] is True

        finalize_node = session_nodes.build_finalize_chat_session_node(
            context=context,
            session=session,
        )
        final_state = await finalize_node(
            {
                **state,
                "turn_id": "turn-1",
                "assistant_response": "这里是在区分一般过去时和现在完成时。",
            }
        )

        finalized = session.get(ChatSession, state["session_id"])
        assert finalized is not None
        assert finalized.title == "完成时辨析"
        assert final_state["session_title"] == "完成时辨析"


@pytest.mark.anyio
async def test_generate_session_title_uses_llm_and_cleans_output(monkeypatch):
    async def fake_completion(messages, **kwargs):
        assert kwargs["model"] == "light"
        assert kwargs["call_purpose"].value == "summarize"
        assert "用户问题：怎么理解 Git 分支协作？" in messages[1]["content"]
        return "标题：Git 分支协作入门。"

    monkeypatch.setattr(sessioning, "acompletion", fake_completion)

    title = await use_cases._generate_session_title(
        subject="Git",
        question="怎么理解 Git 分支协作？",
        selected_text="feature/payment-integration",
        assistant_response="分支让不同任务在独立开发路径上并行推进。",
    )

    assert title == "Git 分支协作入门"


@pytest.mark.anyio
async def test_generate_session_title_falls_back_when_llm_fails(monkeypatch):
    async def fake_completion(_messages, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(sessioning, "acompletion", fake_completion)
    question = "这是一段很长很长的问题内容，用来确认标题失败时会回退到本地标题"

    title = await use_cases._generate_session_title(
        subject="Git",
        question=question,
        selected_text=None,
        assistant_response="",
    )

    assert title == use_cases._build_session_title(question)
