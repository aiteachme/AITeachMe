from app.shared.infra.tools.builtin.markdown_processing import validate_single_file_html
from app.workflows.digest.docgen.lib.interactive_design import assess_interactive_html_quality
from app.workflows.digest.docgen.lib.interactive_html import (
    _generated_html_completeness_issues,
    _javascript_syntax_issues,
    _node_executable_path,
    _non_ascii_javascript_identifier_issues,
    _suspicious_unquoted_identifier_issues,
)
from app.workflows.digest.docgen.lib.interactive_widgets import (
    ALLOWED_INTERACTIVE_WIDGET_TYPES,
    InteractiveSceneOutline,
)


def test_interactive_html_quality_rejects_static_card() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>等价无穷小</title>
</head>
<body>
  <main>
    <h1>等价无穷小替换</h1>
    <p>sinx ~ x, tanx ~ x</p>
    <div style="width:320px;height:160px;background:#ccc"></div>
    <button>重置</button>
  </main>
</body>
</html>"""

    report = assess_interactive_html_quality(
        html,
        title="等价无穷小替换",
        context="通过调节 x 观察 sinx 与 x 的比值和误差。",
        design_brief="- 展示方向：局部变化观察；观察曲线、比值、误差如何随状态改变。",
    )

    assert not report.passed
    assert "缺少学生能主动操作的控件或交互事件。" in report.issues
    assert "设计 brief 已建立可观察变化合同，但页面没有 SVG/Canvas 或真实 DOM 等清晰图形载体。" in report.issues


def test_visualization3d_is_temporarily_disabled_for_outline_selection() -> None:
    outline = InteractiveSceneOutline.model_validate({
        "type": "interactive",
        "title": "空间结构",
        "widgetType": "visualization3d",
    })

    assert "visualization3d" not in ALLOWED_INTERACTIVE_WIDGET_TYPES
    assert outline.widgetType == "diagram"


def test_interactive_html_quality_accepts_state_driven_svg() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>等价无穷小</title>
</head>
<body>
  <main>
    <h1>等价无穷小替换</h1>
    <label>x 值 <input id="x" type="range" min="1" max="100" value="20" /></label>
    <button id="reset">重置</button>
    <svg viewBox="0 0 320 180" role="img" aria-label="sinx 与 x 的比值曲线">
      <path id="ratio" d="M10 160 L160 90 L310 30" fill="none" stroke="#2563eb" stroke-width="4" />
      <circle id="point" cx="160" cy="90" r="6" fill="#dc2626" />
    </svg>
    <p id="feedback">观察提示：x 越接近 0，比值 sinx/x 越接近 1。</p>
  </main>
  <script>
    const slider = document.getElementById("x");
    const point = document.getElementById("point");
    const feedback = document.getElementById("feedback");
    function update() {
      const t = Number(slider.value) / 100;
      point.setAttribute("cx", String(10 + t * 300));
      point.setAttribute("cy", String(160 - t * 120));
      feedback.textContent = "观察提示：当前比值正在靠近 1，误差会随 x 缩小。";
    }
    slider.addEventListener("input", update);
    document.getElementById("reset").addEventListener("click", () => {
      slider.value = "20";
      update();
    });
    update();
  </script>
</body>
</html>"""

    report = assess_interactive_html_quality(
        html,
        title="等价无穷小替换",
        context="通过调节 x 观察 sinx 与 x 的比值和误差。",
        design_brief="- 展示方向：局部变化观察；观察曲线、比值、误差如何随状态改变。",
    )

    assert report.passed
    assert report.issues == ()


def test_interactive_html_quality_accepts_dynamic_three_canvas() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>空间结构</title>
</head>
<body>
  <main>
    <h1>空间结构</h1>
    <p>拖动视角观察 3D 结构。</p>
    <button id="reset-btn">Reset</button>
  </main>
  <script>
    const canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    const scene = { add() {} };
    const renderer = { domElement: canvas, render() {} };
    const controls = { update() {} };
    scene.add(canvas);
    function animate() {
      controls.update();
      renderer.render();
      requestAnimationFrame(animate);
    }
    window.addEventListener("message", function () {});
    animate();
  </script>
</body>
</html>"""

    report = assess_interactive_html_quality(
        html,
        title="空间结构",
        context="通过 3D 视角观察空间结构。",
        design_brief="- 展示方向：观察 3D 结构如何随视角变化。",
    )

    assert report.passed
    assert report.issues == ()


def test_validate_single_file_html_allows_whitelisted_importmap_cdn_only() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D</title>
  <script type="importmap">
  {"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js"}}
  </script>
</head>
<body>
  <canvas></canvas>
</body>
</html>"""

    assert validate_single_file_html(
        html,
        allow_external_resources=True,
        allowed_resource_hosts={"unpkg.com"},
    ) == []
    assert "HTML sidecar 包含未允许的远程资源域名：evil.example。" in validate_single_file_html(
        html.replace("unpkg.com", "evil.example"),
        allow_external_resources=True,
        allowed_resource_hosts={"unpkg.com"},
    )
    assert "HTML sidecar 包含远程资源 URL。" in validate_single_file_html(html)


def test_generated_html_completeness_detects_truncated_raw_output() -> None:
    raw = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>半截输出</title>
</head>
<body>
  <canvas id="demo"></canvas>
  <script>
    function animate() {
      requestAnimationFrame(animate);
"""

    issues = _generated_html_completeness_issues(raw)

    assert "模型输出的原始 HTML 缺少 </body>，可能尚未生成完整。" in issues
    assert "模型输出的原始 HTML 缺少 </html>，可能尚未生成完整。" in issues
    assert "模型输出的原始 HTML 存在未闭合的 <script>，可能被截断。" in issues


def test_javascript_syntax_check_rejects_broken_generated_script() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D</title>
</head>
<body>
  <script type="application/json" id="widget-config">{"type":"visualization3d"}</script>
  <script type="module">
    const target = ;
  </script>
</body>
</html>"""

    issues = _javascript_syntax_issues(html)

    assert issues
    assert "JavaScript 脚本存在语法错误" in issues[0]


def test_visualization3d_check_rejects_unquoted_identifier_values() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D</title>
</head>
<body>
  <script type="module">
    const objects = [{ id: ljnup, label: "结构" }];
  </script>
</body>
</html>"""

    issues = _suspicious_unquoted_identifier_issues(html, "visualization3d")

    assert issues == ['JavaScript 里疑似把文本/ID 写成了未加引号的标识符：ljnup。应写成字符串 "ljnup"。']


def test_visualization3d_check_rejects_unicode_unquoted_identifier_values() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D</title>
</head>
<body>
  <script type="module">
    const objects = [{ id: նյութ, label: "结构" }];
  </script>
</body>
</html>"""

    issues = _suspicious_unquoted_identifier_issues(html, "visualization3d")

    assert issues == ['JavaScript 里疑似把文本/ID 写成了未加引号的标识符：նյութ。应写成字符串 "նյութ"。']


def test_visualization3d_check_rejects_non_ascii_javascript_identifiers() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D</title>
</head>
<body>
  <script type="module">
    const նյութ = { label: "结构" };
  </script>
</body>
</html>"""

    issues = _non_ascii_javascript_identifier_issues(html, "visualization3d")

    assert issues == [
        '3D JavaScript 里出现非 ASCII 裸标识符：նյութ。变量名必须使用英文/ASCII；如果这是文本、标签、ID 或术语，必须写成字符串 "նյութ"。'
    ]


def test_node_executable_path_finds_conda_node() -> None:
    assert _node_executable_path()
