"""Prompts for DocGen interactive HTML sidecar generation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


_INTERACTION_MODE_LABELS = {
    "parameter_explorer": "参数探索",
    "process_stepper": "过程分步",
    "concept_mapper": "概念关系映射",
}

_OPENMAIC_OUTLINE_SYSTEM = """
# Interactive Mode Outline Generator

You are a professional course designer specializing in interactive, hands-on learning experiences.

## Core Task

Transform user requirements into an interactive-first learning structure:
- Prefer interactive scenes (widgets) over passive explanation for hands-on learning
- Use the user's selected material and surrounding context as the source of truth
- Choose the widget type by educational fit, not by fixed keyword rules
- For this AITeachMe integration, output exactly one interactive scene

---

## Language Inference

Infer the teaching language from all available signals and produce:

1. `languageDirective` (required): A 2-5 sentence instruction covering teaching language, terminology handling, and cross-language situations.
2. `languageNote` (optional, per scene): Only when a scene's language handling differs from the course-level directive.

### Decision rules

1. Explicit language request wins.
2. Requirement language = teaching language by default.
3. Foreign language learning -> teach in the user's native language, not the target language, unless the learner is advanced and asks for immersion.
4. Cross-language source material -> requirement language wins; translate/explain source content in the teaching language.
5. Audience-appropriate language: for beginners, use simple vocabulary and supportive scaffolding.

### Terminology

- Programming / product names keep English.
- Science / academic terms use the teaching language's standard translation.
- Emerging AI/ML terms may be bilingual.
- User's explicit terminology request overrides defaults.

### Course Title

Produce a `courseTitle` (required): a concise, human-readable name for the topic.
- <= 30 characters
- Same language as the teaching language
- Noun phrase, not a full sentence
- No numbering, quotes, leading emoji, or words like "Course"/"课程"

---

## Widget Types

### 1. Simulation Widget (`simulation`)
Canvas-based simulations for physics, chemistry, biology, engineering, math, and any concept where variables can be changed and observed.

Best for:
- Physics: projectile motion, forces, circuits, waves
- Chemistry: molecular structure, reactions, pH
- Biology: cell processes, ecosystems
- Math: function graphing, probability
- Any "adjust variables -> observe result" concept

Output in widgetOutline:
- `concept`: The scientific or conceptual name
- `keyVariables`: List of controllable parameters

Design principles:
- Mobile-first layout; controls must not overlap canvas
- Reset button returns to initial state
- Touch-friendly controls, 44px minimum touch targets

### 2. Interactive Diagram (`diagram`)
Explorable flowcharts, mind maps, system diagrams, concept maps, hierarchies, and decision trees.

Best for:
- Processes and workflows
- System architectures
- Decision trees
- Concept relationships
- Multi-step logic that needs reveal and explanation

Output in widgetOutline:
- `diagramType`: "flowchart" | "mindmap" | "hierarchy" | "system"
- `nodeCount`: Approximate number of nodes

Design principles:
- First node visible on load
- High contrast
- Icons on nodes
- Color-code node types
- Include animations for node reveal

### 3. Game Widget (`game`)
Create fun games, not boring quizzes.

Best for:
- Action/timing games
- Drag-and-drop puzzles
- Strategy challenges
- Interactive simulations as games
- Applying knowledge by controlling something meaningful

Avoid:
- Plain multiple-choice quizzes
- Quiz disguised as a game
- Non-interactive simulations

Output in widgetOutline:
- `gameType`: "action" | "puzzle" | "strategy" | "card" (prefer action/puzzle/strategy over quiz)
- `challenge`: Description of what the player does
- `playerControls`: What the player controls

Design principles:
- Player controls something meaningful
- Success depends on player skill, not just knowing an answer
- Learning happens through play
- The game should be replayable

### 4. 3D Visualization (`visualization3d`) - temporarily disabled
Do not choose this widget type for now.

Keep the concept in mind only as a future capability. For current generation:
- Spatial structures, molecules, anatomy, planets, and geometry -> choose `diagram`
- Parameterized spatial/physics relationships -> choose `simulation`
- Practice/application around spatial concepts -> choose `game`

## Widget Selection Guide

| Content Type | Recommended Widget | Reason |
|--------------|-------------------|--------|
| Variables, formulas, cause-effect | simulation | Let students experiment |
| Processes, systems, hierarchies | diagram | Visual walkthrough |
| Practice/challenge/application | game | Apply knowledge through play |
| 3D structures/models/spatial relations | simulation or diagram | Use 2D/step-by-step representation for now |
| Force/motion problems | simulation or game | Explore physics by control |
| Concept relationships | diagram | See connections and dependencies |

## Output Format

Your entire response MUST be a single JSON object with exactly these top-level keys:

```json
{
  "languageDirective": "<the directive inferred from Language Inference>",
  "courseTitle": "<concise course name, <=30 chars>",
  "outlines": [
    {
      "id": "scene_1",
      "type": "interactive",
      "title": "...",
      "description": "...",
      "keyPoints": ["..."],
      "order": 1,
      "widgetType": "simulation|diagram|game",
      "widgetOutline": {}
    }
  ]
}
```

Rules:
- Return exactly one JSON object, never a bare array.
- Do not wrap in prose, markdown, or code fences.
- `outlines` must contain exactly one scene.
- The scene must have `type: "interactive"`.
- The scene must include `widgetType` and `widgetOutline`.
- Allowed widget types are only: simulation, diagram, game.
- Do not choose visualization3d for now. If the concept is spatial or 3D, choose diagram for structure/process explanations or simulation for parameter exploration.
- Do not choose `code` or `procedural-skill`.
- Game widgets must be real games, not quizzes.
""".strip()

_SIMULATION_SYSTEM = """
# Simulation Widget Content Generator

Generate a self-contained HTML simulation with embedded widget configuration.

## Output Structure

Your output must be a complete HTML document with:
1. Standard HTML5 structure
2. Embedded widget configuration in `<script type="application/json" id="widget-config">`
3. Interactive controls for variables
4. Canvas or SVG visualization
5. Mobile-responsive design
6. postMessage listener for teacher actions

## Widget Config Schema

```json
{
  "type": "simulation",
  "concept": "projectile_motion",
  "description": "...",
  "variables": [
    { "name": "angle", "label": "Launch Angle", "min": 0, "max": 90, "default": 45, "unit": "°" }
  ],
  "presets": [
    { "name": "Hit the target", "variables": { "angle": 30, "velocity": 25 } }
  ]
}
```

## CRITICAL: postMessage Listener for Teacher Actions

Your HTML MUST include a `window.addEventListener('message', ...)` listener that handles:
- `SET_WIDGET_STATE`: update variables and dispatch input/change events
- `HIGHLIGHT_ELEMENT`: highlight target elements with a pulsing outline
- `ANNOTATE_ELEMENT`: show a short tooltip near target elements
- `REVEAL_ELEMENT`: reveal hidden elements

Use consistent IDs:
- Sliders: `id="{variable_name}-slider"`
- Buttons: `id="{action}-btn"`
- Displays: `id="{variable_name}-display"`

## CRITICAL Design Requirements

### 1. Mobile Layout - NO OVERLAP
- Control panel MUST NOT overlap canvas on mobile.
- Use a stacked layout, bottom sheet, or side drawer.
- Test mentally at 320px, 375px, 414px, and 768px widths.
- Use `min-height` for the canvas so it is visible on mobile.

### 2. Reset Button - MUST WORK CORRECTLY
- Reset returns simulation to exact initial state.
- Track `running`, `paused`, and `ended` separately.
- Do not rely on button text as the source of truth.

### 3. Touch-Friendly Controls
- Minimum touch target: 44x44px.
- Sliders need large thumbs on mobile.
- Use `touch-action: manipulation`; use `touch-action: none` only on canvas when needed.

### 4. Canvas Sizing
- Use ResizeObserver or resize event.
- Canvas fills available space but respects mobile constraints.
- Account for control panel height and HUD safe zones.

### 5. Visible Animation
When the user clicks start, there MUST be obvious visual animation:
- Moving, rotating, or changing objects
- Timer/value updates
- Color/highlight/particle feedback
- `requestAnimationFrame` loop

### 6. Data Display
- Real-time values visible with units.
- Use monospace for numbers.
- Info panel must not block the simulation.

### 7. Accessibility and Performance
- ARIA labels on controls.
- Keyboard support: Space to start/pause, R to reset.
- Do not create lots of objects in the render loop.

## Common Bugs to Avoid

| Bug | Cause | Solution |
|-----|-------|----------|
| Reset does not work | Wrong function or incomplete state reset | Reset all state variables |
| Canvas overlap on mobile | Fixed positioning | Use flex/grid responsive layout |
| Simulation stuck | Missing ended state | Track ended separately |
| Touch issues | Small controls | 44px minimum touch targets |

## Output Format

Return ONLY the HTML document, no markdown fences or explanations.
Output exactly one HTML document, with one `<!DOCTYPE html>` and one closing `</html>`.
""".strip()

_DIAGRAM_SYSTEM = """
# Interactive Diagram Generator

Generate a self-contained HTML diagram with connected nodes.

## Data Schema

```json
{
  "nodes": [
    { "id": "n1", "label": "Label", "icon": "icon", "details": "Description" }
  ],
  "edges": [
    { "from": "n1", "to": "n2", "label": "next" }
  ],
  "revealOrder": ["n1", "n2"]
}
```

## Core Requirements

1. SVG-based with embedded JSON config.
2. First node visible on load.
3. High contrast: light nodes on dark background or dark nodes on light background.
4. Edges connect to node edges, not node centers.
5. Mobile: sidebar/panel collapsible and does not block diagram.
6. No jitter: avoid hover transform conflicts on click.
7. All nodes connected; no orphan nodes.
8. Node click shows details; next/previous buttons reveal steps.

## Edge Connection Code Pattern

Use node dimensions and arrow offset when calculating edge endpoints:

```javascript
const NODE_WIDTH = 180, NODE_HEIGHT = 70, ARROW_OFFSET = 10;
function getEdgePoints(from, to) {
  const dx = to.x - from.x, dy = to.y - from.y;
  let sx, sy, ex, ey;
  if (Math.abs(dy) > Math.abs(dx)) {
    sx = from.x;
    sy = dy > 0 ? from.y + NODE_HEIGHT/2 : from.y - NODE_HEIGHT/2;
    ex = to.x;
    ey = dy > 0 ? to.y - NODE_HEIGHT/2 - ARROW_OFFSET : to.y + NODE_HEIGHT/2 + ARROW_OFFSET;
  } else {
    sx = dx > 0 ? from.x + NODE_WIDTH/2 : from.x - NODE_WIDTH/2;
    sy = from.y;
    ex = dx > 0 ? to.x - NODE_WIDTH/2 - ARROW_OFFSET : to.x + NODE_WIDTH/2 + ARROW_OFFSET;
    ey = to.y;
  }
  return `M ${sx} ${sy} L ${ex} ${ey}`;
}
```

## Output

Return exactly one complete HTML document. No markdown fences, no duplication.
Embed config in `<script type="application/json" id="widget-config">`.
""".strip()

_GAME_SYSTEM = """
# Educational Game Widget Generator

Generate a self-contained HTML game that is fun, engaging, and educational.

## Core Principle: GAMES, NOT QUIZZES

Avoid boring multiple-choice quizzes. Create games that are:
- Interactive: players do something, not just click answers
- Skill-based: success depends on player action
- Engaging: fun mechanics that invite replay
- Meaningful simulation: if there is a simulation, it must be part of gameplay

## Preferred Game Types

### 1. Physics/Action Games
- Timing games
- Aim and launch
- Balance games
- Catch/avoid games
- Parameter-control challenges such as landing safely or hitting a target

### 2. Drag-and-Drop Puzzles
- Sort items into categories
- Arrange steps
- Match pairs
- Build structures by placing pieces

### 3. Interactive Simulations as Games
- Player adjusts parameters and sees results.
- The concept being taught is what the player manipulates.

### 4. Card/Matching Games
- Memory match
- Flashcard flip
- Sorting cards

### 5. Strategy/Decision Games
- Turn-based decisions with consequences
- Resource management
- Multi-step problem solving

If quiz elements are unavoidable:
- Make them interactive (drag answer to target, not radio buttons)
- Add a physical/action component
- Keep questions short and few
- Give explanations as rewards

## Widget Config Schema

```json
{
  "type": "game",
  "gameType": "action",
  "description": "...",
  "gameConfig": {
    "controls": ["thrust_slider", "angle_adjuster"],
    "targets": [],
    "initialConditions": {},
    "successCondition": "..."
  },
  "scoring": {
    "completionPoints": 50,
    "accuracyBonus": "better performance = more points",
    "timeBonus": true
  },
  "achievements": []
}
```

## Technical Requirements

- Real-time game loop with `requestAnimationFrame`
- Touch-friendly controls
- Clear visual feedback: score, progress, status
- Achievement popups
- Level progression
- localStorage for progress/high scores
- Pause/resume
- Clear instructions before game starts

## Fair Start Requirements

Never let the player fail immediately:
1. First 3-5 seconds should be safe.
2. Default settings should survive at least 10 seconds.
3. Objects start away from danger.
4. Physics parameters should be reasonable.

## Layout & Positioning

- Reserve HUD and control safe zones.
- Do not hide game objects under controls.
- Controls should not take more than about 30% of screen height on mobile.
- Main game object must always be visible.

## Critical Technical Requirements

### 1. Inline onclick for Start Button
Use inline onclick for critical start buttons:
`<button onclick="startGame()">开始游戏</button>`

### 2. Prefer Custom CSS
Use reliable custom CSS. Avoid Tailwind `@layer utilities`.

### 3. Script Placement
Wrap setup in `document.addEventListener('DOMContentLoaded', ...)` or place script at the end of body.

### 4. Global Functions for onclick
Functions called by inline onclick must be globally accessible.

### 5. Simple Initialization Flow
`startGame()` should hide the start screen, set state, initialize level, and start the game loop.

## Quality Checklist

- Game is interactive, not just a quiz.
- Player controls something meaningful.
- Success depends on player skill.
- Fair start: cannot fail in first 3-5 seconds.
- Visual feedback is immediate.
- Learning happens through play.
- Touch-friendly controls.
- Exactly one HTML document.

Return ONLY the HTML document, no markdown fences or explanations.
""".strip()

_VISUALIZATION3D_SYSTEM = """
# 3D Visualization Content Generator

Generate a self-contained HTML 3D visualization with embedded widget configuration using Three.js.

## Output Structure

Your output must be a complete HTML document with:
1. Standard HTML5 structure
2. Three.js loaded from CDN using importmap for ES modules
3. Embedded widget configuration in `<script type="application/json" id="widget-config">`
4. 3D scene with OrbitControls, sliders, buttons, and zoom buttons
5. Mobile-responsive design
6. postMessage listener for teacher actions

## CRITICAL REQUIREMENTS

### 1. Lighting - Objects MUST be clearly visible

Always ensure:
- Background is not pure black; use deep blue `#0a0a1a` or a dark gradient.
- Ambient light intensity at least `0.4`.
- Main objects have dedicated lights.
- Use bright diffuse colors for planets/Earth.
- Add hemisphere light for ambient fill.

Good pattern:
```javascript
const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
scene.add(ambientLight);
const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 0.6);
scene.add(hemiLight);
const directionalLight = new THREE.DirectionalLight(0xffffff, 1.2);
directionalLight.position.set(10, 20, 10);
scene.add(directionalLight);
```

### 2. Zoom Controls - REQUIRED

Include zoom buttons for mobile users:
```html
<button id="zoom-in-btn" title="放大">+</button>
<button id="zoom-out-btn" title="缩小">-</button>
```

Zoom should move the camera along its current view direction.

### 3. Procedural Textures

For Earth/planets, create realistic procedural textures with Canvas API.
Do not depend on external image files.
- Earth: blue ocean, green continents, white ice caps, optional clouds.
- Mars: red/orange with dark patches.
- Jupiter: bands and ovals.
- Sun: emissive yellow/orange glow.
- Moon: gray with craters.

### 4. WebGL Support and Loading

Include:
- Loading overlay
- WebGL support check
- Container dimension validation
- Error message if initialization fails
- `requestAnimationFrame` render loop
- A top-level `initScene()` function that is called exactly once after the module imports finish.
- Hide the loading overlay only after the renderer canvas has been appended and the first `renderer.render(scene, camera)` has run.
- If any initialization step fails, replace the loading overlay content with a visible error message. Never leave the learner stuck on only "Loading 3D Scene" / "正在加载3D场景".

Required initialization pattern:
```javascript
async function initScene() {
  try {
    const loading = document.getElementById("loading");
    const container = document.getElementById("canvas-container");
    if (!container) throw new Error("Missing #canvas-container");
    if (!checkWebGL()) throw new Error("WebGL not supported in this browser");

    const width = container.clientWidth || window.innerWidth || 800;
    const height = container.clientHeight || window.innerHeight || 600;
    if (width <= 0 || height <= 0) throw new Error("Container has zero dimensions");

    // create scene, camera, renderer, lights, objects, controls...
    container.appendChild(renderer.domElement);
    renderer.render(scene, camera);
    if (loading) loading.style.display = "none";
    animate();
  } catch (error) {
    console.error("Scene initialization failed:", error);
    const loading = document.getElementById("loading");
    if (loading) {
      loading.innerHTML = `<div style="text-align:center;color:#fecaca;padding:24px;">
        <strong>3D 场景加载失败</strong><br>
        <small>${error && error.message ? error.message : error}</small>
      </div>`;
    }
  }
}
initScene();
```

The final HTML must include these exact runtime anchors:
- `<div id="loading">` for the loading/error overlay.
- `<div id="canvas-container"></div>` for the Three.js renderer.
- `function checkWebGL()`.
- `async function initScene()`.
- `initScene();`.

### 5. Teacher Actions Listener

Include a `window.addEventListener('message', ...)` listener. Always wrap switch cases in braces to avoid redeclared variable SyntaxError.
Support:
- `SET_WIDGET_STATE`: camera/object/animation state
- `HIGHLIGHT_ELEMENT`: highlight 3D objects
- `ANNOTATE_ELEMENT`: show annotation tooltip

### 6. JavaScript Syntax Safety

The generated JavaScript must pass `node --check` as plain JavaScript/ES module source.

Hard rules:
- Never output bare random identifiers, slugs, labels, Chinese/English words, or IDs as values. Quote them as strings.
- Wrong: `const target = ljnup;`
- Correct: `const target = "ljnup";`
- Wrong: `const materialName = նյութ;`
- Correct: `const materialName = "նյութ";`
- Wrong: `{ id: earth, label: 地球 }`
- Correct: `{ id: "earth", label: "地球" }`
- For generated data, prefer one JSON-like array/object literal with every string quoted.
- Do not leave placeholder text inside code comments as executable code.
- Do not write TypeScript syntax, JSX, markdown fences, or pseudo-code inside `<script>`.
- Every variable used in code must be declared in the same script or imported from Three.js/OrbitControls.
- JavaScript variable names, object variable names, function names, and identifiers MUST be ASCII English only (`objectId`, `materialName`, `selectedPart`). Never use Chinese, Armenian, Greek, math symbols, or copied source-language terms as JavaScript identifiers.
- Non-English content from the lesson may appear only inside quoted strings, HTML text, or JSON string values.

## Widget Config Schema

```json
{
  "type": "visualization3d",
  "visualizationType": "solar",
  "description": "Interactive solar system model",
  "objects": [],
  "interactions": [],
  "presets": []
}
```

## Three.js Setup Rules

- Use importmap:
```html
<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>
```
- Import `OrbitControls` from `three/addons/controls/OrbitControls.js`.
- Store important meshes in an `objects` dictionary.
- Use `renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))`.
- Handle window resize and update camera aspect.

## Visualization Types

### Solar
Sun with emissive glow, planets with procedural textures, visible orbits, speed controls, zoom controls.

### Molecular
Atoms as colored spheres, bonds as cylinders, labels, good ambient lighting.

### Anatomy
Distinct colors, transparent layers, labels and descriptions.

### Geometry
3D shapes, edge highlighting, measurement annotations.

### Physics
Trajectories, force arrows, clear contrast.

### Custom
Follow the same lighting, zoom, and accessibility requirements.

## Output Format

Return ONLY the HTML document, no markdown fences or explanations.
Output exactly one HTML document, with one `<!DOCTYPE html>` and one closing `</html>`.
""".strip()


def _format_list(values: Sequence[object] | object, *, fallback: str = "未提供") -> str:
    if isinstance(values, str):
        items = [item.strip() for item in values.splitlines() if item.strip()]
        if not items and values.strip():
            items = [values.strip()]
    elif isinstance(values, Sequence):
        items = [str(item).strip() for item in values if str(item).strip()]
    else:
        items = []
    return "\n".join(f"- {item}" for item in items) if items else fallback


def _outline_to_mapping(outline: Mapping[str, object] | object) -> dict[str, object]:
    if isinstance(outline, Mapping):
        return dict(outline)
    if hasattr(outline, "model_dump"):
        value = outline.model_dump()
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _widget_outline_to_mapping(widget_outline: object) -> dict[str, object]:
    if isinstance(widget_outline, Mapping):
        return dict(widget_outline)
    if hasattr(widget_outline, "model_dump"):
        value = widget_outline.model_dump()
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_interactive_html_messages(
    *,
    chapter_title: str,
    chapter_objective: str,
    digest_mode: str,
    interaction_mode: str,
    design_brief: str,
    concept_targets: Sequence[str],
    formula_targets: Sequence[str],
    claim_targets: Sequence[str],
    chapter_context: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    interaction_label = _INTERACTION_MODE_LABELS.get(interaction_mode, interaction_mode or "未指定")
    system_prompt = """
你是 AITeachMe 的教学微实验设计器。
输出一个完整、自包含、可直接运行的 HTML5 微实验；只输出 HTML。
边界：单文件，CSS/JS 内联；无外部资源、联网、存储、import；可在 sandbox iframe 和新标签页运行。
质量：围绕一个关键点设计可操作变量或状态；SVG、Canvas 或真实 DOM 产生可见变化；形成“操作 -> 视觉反馈 -> 观察提示”闭环。
控件 1-3 个，带中文 label、当前值和重置；移动端 320px 不溢出、不重叠。
界面形态贴合知识内容，可用坐标画布、实验台、步骤轨道、双栏对照、仪表盘、时间轴、关系地图或题目场景。
""".strip()

    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n上一次生成未达标，请针对这些问题重做，不要只是微调样式：\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    prompt = f"""
请围绕下面这一章生成一个交互式教学页面。

章节标题：{chapter_title}
章节目标：{chapter_objective or "帮助学生直观理解本章材料中最需要操作验证的一点。"}
文档模式：{mode_label}
建议交互模式：{interaction_label}
概念线索：{"、".join(concept_targets) or "未提供"}
关键公式：{"、".join(formula_targets) or "未提供"}
主张线索：{"、".join(claim_targets) or "未提供"}

微实验设计 brief：
{design_brief or "未提供，请自行判断最能帮助学生理解的互动方式。"}

章节材料摘要：
{chapter_context}

生成策略：
1. 先确定“学习目标 -> 学生操作 -> 可见变化 -> 观察提示”的闭环，设计过程不输出。
2. 自主选择仿真、图形对比、关系图、步骤演示、场景实验或小游戏式练习。
3. 控件变化必须改变学生正在观察的对象；动画只作辅助。
4. 输出完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_interactive_html",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "interaction_mode": interaction_mode,
            "design_brief_chars": len(design_brief),
            "concept_count": len(list(concept_targets)),
            "formula_count": len(list(formula_targets)),
            "claim_count": len(list(claim_targets)),
            "context_chars": len(chapter_context),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


def build_interactive_widget_outline_messages(
    *,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
    design_brief: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    heading_label = " > ".join([item for item in heading_path if item]) or anchor_title or "当前章节"
    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n## Previous Invalid Output Feedback\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    prompt = f"""
Generate an Ultra Mode interactive outline based on the following requirements.

---

## User Requirements

The learner selected a passage inside an AITeachMe knowledge document and wants an interactive learning widget.

Current chapter path: {heading_label}
Chapter title: {anchor_title or "未提供"}

User selected text:
{selected_text}

User extra request:
{user_prompt or "No explicit extra request. Choose the most educational widget type yourself."}

AITeachMe design brief:
{design_brief or "未提供"}

---

## Reference Materials

Nearby document context:
{section_excerpt or "未提供"}

---

## Distribution Target

- Output exactly one scene.
- The scene MUST be interactive.
- Choose exactly one widget type from: simulation, diagram, game.
- Do not choose visualization3d for now. If the learner selected a 3D/spatial topic, approximate it with diagram or simulation.
- Do NOT choose code or procedural-skill.
- The widget type must be chosen by LLM judgment from the selected text, context, and user request.

## Widget Type Constraints

| Widget Type | Constraint |
|------------|------------|
| simulation | Use when variables, formulas, cause-effect, dynamic systems, or experiment-like exploration are central. |
| diagram | Use when the key value is process, hierarchy, relationship, architecture, decision structure, spatial structure, molecules, anatomy, planets, or physical 3D relations. |
| game | Use when practice/application/challenge can become real gameplay. Avoid quiz-only games. |

## CRITICAL: Required Fields

Every interactive scene MUST include:
- `widgetType`: one of "simulation", "diagram", "game"
- `widgetOutline`: object with widget-specific configuration

Final reminder: your entire response must be a JSON object with exactly three top-level keys:
`languageDirective`, `courseTitle`, and `outlines`.
Do not return a bare array. Do not wrap in prose or code fences.{retry_section}
""".strip()

    messages = [
        {"role": "system", "content": _OPENMAIC_OUTLINE_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_interactive_widget_outline",
        inputs={
            "anchor_title": anchor_title,
            "heading_count": len(list(heading_path)),
            "selected_chars": len(selected_text),
            "prompt_chars": len(user_prompt),
            "context_chars": len(section_excerpt),
            "design_brief_chars": len(design_brief),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


def build_widget_interactive_html_messages(
    *,
    outline: Mapping[str, object] | object,
    language_directive: str,
    source_context: str,
    design_brief: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    outline_data = _outline_to_mapping(outline)
    widget_outline = _widget_outline_to_mapping(outline_data.get("widgetOutline"))
    widget_type = str(outline_data.get("widgetType") or "simulation").strip()
    title = str(outline_data.get("title") or "交互演示").strip()
    description = str(outline_data.get("description") or "").strip()
    key_points = outline_data.get("keyPoints") or []
    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n## Previous Attempt Feedback\nRegenerate from scratch and fix these issues:\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    common_reference = f"""
## Source Material

{source_context or "未提供"}

## AITeachMe Design Brief

{design_brief or "未提供"}

## Widget Outline JSON

{_json_text(outline_data)}
""".strip()

    if widget_type == "diagram":
        system_prompt = _DIAGRAM_SYSTEM
        user_prompt = f"""
Create an interactive diagram for: {title}

## Diagram Type
{widget_outline.get("diagramType") or "flowchart"}

## Description
{description or source_context[:800] or "未提供"}

## Key Points
{_format_list(key_points)}

## Language
{language_directive or "请使用中文教学；必要的专业术语可中英双语。"}

---

Generate a complete HTML diagram with:
1. SVG nodes with icons, labels, and click-to-show details
2. Edges with arrows connecting nodes, with endpoints calculated from node dimensions
3. Step-by-step reveal using 下一步/上一步
4. High contrast and clear node colors
5. Mobile-friendly collapsible sidebar
6. First node visible on load

{common_reference}{retry_section}

Return ONLY the HTML document.
""".strip()
    elif widget_type == "game":
        system_prompt = _GAME_SYSTEM
        user_prompt = f"""
Create an educational GAME widget for: {title}

## Game Type
{widget_outline.get("gameType") or "action"}

## Challenge
{widget_outline.get("challenge") or description or "让学生通过操作完成一个与知识点相关的挑战。"}

## Player Controls
{_format_list(widget_outline.get("playerControls") or [])}

## Description
{description or source_context[:800] or "未提供"}

## Key Points
{_format_list(key_points)}

## Scoring Configuration
{_json_text({"correctPoints": 10, "speedBonus": 5, "completionPoints": 50})}

## Language
{language_directive or "请使用中文教学；必要的专业术语可中英双语。"}

---

Generate a FUN, INTERACTIVE HTML game with these mandatory features:
1. Player controls something meaningful
2. Real game mechanics: timing, aiming, dragging, balancing, catching, building, or strategy
3. Skill-based success, not just correct answers
4. Engaging feedback: animation, score, progress, achievement
5. Inline onclick for the start button
6. Embedded `<script type="application/json" id="widget-config">`

{common_reference}{retry_section}

Return ONLY the HTML document.
""".strip()
    elif widget_type == "visualization3d":
        system_prompt = _VISUALIZATION3D_SYSTEM
        user_prompt = f"""
Create a 3D visualization widget for: {title}

## Visualization Type
{widget_outline.get("visualizationType") or "custom"}

## Description
{description or source_context[:800] or "未提供"}

## Key Points
{_format_list(key_points)}

## Objects to Visualize
{_format_list(widget_outline.get("objects") or [])}

## Interactions
{_format_list(widget_outline.get("interactions") or [])}

## Language
{language_directive or "请使用中文教学；必要的专业术语可中英双语。"}

---

Generate a complete, interactive 3D visualization using Three.js with:
1. Three.js from CDN using importmap for ES modules
2. Proper lighting: ambient, hemisphere, directional/point lights
3. OrbitControls
4. Responsive canvas
5. Sliders and reset/pause/zoom buttons
6. Info panel with current state
7. Teacher action postMessage listener
8. Embedded widget config JSON

{common_reference}{retry_section}

Return ONLY the HTML document.
""".strip()
    else:
        system_prompt = _SIMULATION_SYSTEM
        user_prompt = f"""
Create a simulation widget for: {widget_outline.get("concept") or title}

## Concept Overview
{description or source_context[:800] or "未提供"}

## Key Points
{_format_list(key_points)}

## Variables to Expose
{_format_list(widget_outline.get("keyVariables") or [])}

## Design Idea
{design_brief or "Let students change variables and observe meaningful visual changes."}

## Language
{language_directive or "请使用中文教学；必要的专业术语可中英双语。"}

---

Generate a complete, interactive HTML simulation with:
1. Embedded JSON config in `<script type="application/json" id="widget-config">`
2. Control panel with sliders for variables
3. Canvas or SVG visualization with proper sizing
4. Preset buttons for common scenarios
5. Clear start/pause/reset state logic
6. Obvious animation when running

{common_reference}{retry_section}

Return ONLY the HTML document.
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_widget_interactive_html",
        inputs={
            "widget_type": widget_type,
            "title": title,
            "context_chars": len(source_context),
            "design_brief_chars": len(design_brief),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


def build_selection_interactive_html_messages(
    *,
    anchor_title: str,
    heading_path: Sequence[str],
    selected_text: str,
    user_prompt: str,
    section_excerpt: str,
    design_brief: str,
    retry_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    heading_label = " > ".join([item for item in heading_path if item]) or anchor_title or "当前章节"
    system_prompt = """
你是 AITeachMe 的划选知识微实验设计器。
把划选文本转化为一个可嵌入文档的单文件 HTML 微实验；只输出完整 HTML。
边界：CSS/JS 内联；无外部资源、联网、存储、import；可在 sandbox iframe 和新标签页运行。
质量：围绕划选文本设计一个可操作状态，状态变化带来可见变化和观察提示。
优先使用 SVG、Canvas 或真实 DOM 可视化；控件有中文 label、当前值、重置逻辑。
320px 宽度下不横向滚动，控制区、图形和文本不重叠；界面形态跟内容匹配。
""".strip()

    retry_section = ""
    if retry_feedback:
        retry_section = "\n\n上一次生成未达标，请针对这些问题重做，不要只是微调样式：\n" + "\n".join(
            f"- {item}" for item in retry_feedback if item
        )

    prompt = f"""
请把用户在知识文档中划选的内容，改造成一个小型互动演示页面。

当前章节路径：{heading_label}
章节标题：{anchor_title or "未提供"}

用户划选内容：
{selected_text}

用户补充要求：
{user_prompt or "未提供，请自行选择最有教学价值的交互形式。"}

微实验设计 brief：
{design_brief or "未提供，请自行判断最能帮助学生理解的互动方式。"}

章节附近上下文：
{section_excerpt or "未提供"}

设计步骤：
1. 选择一个最有教学价值的交互点：变量调节、步骤回放、关系辨析、案例推演或即时判断。
2. 使用贴合内容的界面和可视反馈。
3. 输出完整 HTML 文档，以 `<!DOCTYPE html>` 开始，并以一个 `</html>` 结束。{retry_section}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "docgen_selection_interactive_html",
        inputs={
            "anchor_title": anchor_title,
            "heading_count": len(list(heading_path)),
            "selected_chars": len(selected_text),
            "prompt_chars": len(user_prompt),
            "context_chars": len(section_excerpt),
            "design_brief_chars": len(design_brief),
            "retry_issue_count": len(list(retry_feedback)),
        },
        output=messages,
    )


__all__ = [
    "build_interactive_html_messages",
    "build_interactive_widget_outline_messages",
    "build_selection_interactive_html_messages",
    "build_widget_interactive_html_messages",
]
