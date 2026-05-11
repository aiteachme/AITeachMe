from app.workflows.digest.docgen.lib.interactive_design import assess_interactive_html_quality


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
    assert "设计 brief 指向连续变化或图形观察，但页面没有 SVG/Canvas 或真实 DOM 等清晰图形载体。" in report.issues


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
