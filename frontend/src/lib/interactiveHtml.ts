export interface InteractiveHtmlPreview {
  mode: "asset" | "auto";
  kind: "interactive" | "figure";
  previewUrl: string;
  assetUrl: string;
  assetPath: string;
  courseId: string;
  title: string;
  planId?: string;
  clientReferenceId?: string;
  overlayId?: string;
  anchorId?: string;
  selectedText?: string;
  prompt?: string;
}

function encodePathSegments(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function normalizeInteractiveAssetPath(raw: string | null): string {
  const normalized = String(raw ?? "").replace(/\\/g, "/").trim().replace(/^\/+/, "");
  if (!normalized || normalized.includes("..")) return "";
  return normalized;
}

export function parseInteractivePreviewHref(
  href: string | undefined,
  options: { fallbackCourseId?: string } = {},
): InteractiveHtmlPreview | null {
  const rawHref = String(href ?? "").trim();
  if (!rawHref) return null;

  const baseUrl = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  let url: URL;
  try {
    url = new URL(rawHref, baseUrl);
  } catch {
    return null;
  }

  if (url.origin !== baseUrl) return null;
  const match = url.pathname.match(/^\/courses\/([^/]+)\/knowledge-docs\/interactive\/?$/);
  const figureMatch = url.pathname.match(/^\/courses\/([^/]+)\/knowledge-docs\/html-figure\/?$/);
  const autoMatch = url.pathname.match(/^\/courses\/([^/]+)\/knowledge-docs\/interactive-auto\/?$/);
  if (!match && !figureMatch && !autoMatch) return null;

  const courseId = (options.fallbackCourseId || decodeURIComponent((match ?? figureMatch ?? autoMatch)?.[1] ?? "")).trim();
  if (!courseId) return null;

  const title = (url.searchParams.get("title") || (figureMatch ? "静态图示" : "交互演示")).trim();
  const previewUrl = `${url.pathname}${url.search}`;

  if (autoMatch) {
    const planId = String(url.searchParams.get("plan") || "").trim();
    const anchorId = String(url.searchParams.get("anchor") || "").trim();
    const selectedText = String(url.searchParams.get("selected") || title).trim();
    if (!planId || !anchorId || !selectedText) return null;
    return {
      mode: "auto",
      kind: "interactive",
      previewUrl,
      assetUrl: "",
      assetPath: `auto/${planId}`,
      courseId,
      title,
      planId,
      clientReferenceId: planId,
      anchorId,
      selectedText,
      prompt: String(url.searchParams.get("prompt") || "").trim(),
    };
  }

  const assetPath = normalizeInteractiveAssetPath(url.searchParams.get("asset"));
  if (!assetPath) return null;

  const assetUrl = `/api/v1/courses/${encodeURIComponent(courseId)}/files/assets/${encodePathSegments(assetPath)}`;
  const anchorId = String(url.searchParams.get("anchor") || "").trim();
  const selectedText = String(url.searchParams.get("selected") || "").trim();

  return {
    mode: "asset",
    kind: figureMatch ? "figure" : "interactive",
    previewUrl,
    assetUrl,
    assetPath,
    courseId,
    title,
    clientReferenceId: String(url.searchParams.get("ref") || "").trim() || undefined,
    overlayId: String(url.searchParams.get("overlay") || "").trim() || undefined,
    anchorId: anchorId || undefined,
    selectedText: selectedText || undefined,
  };
}

const STORAGE_SHIM = `<script data-aiteachme-iframe-storage-shim>
(function () {
  function makeStore() {
    var data = Object.create(null);
    return {
      getItem: function (k) { k = String(k); return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
      setItem: function (k, v) { data[String(k)] = String(v); },
      removeItem: function (k) { delete data[String(k)]; },
      clear: function () { data = Object.create(null); },
      key: function (i) { var keys = Object.keys(data); return i < keys.length ? keys[i] : null; },
      get length() { return Object.keys(data).length; }
    };
  }
  ['localStorage', 'sessionStorage'].forEach(function (name) {
    var ok = false;
    try {
      var s = window[name];
      if (s) {
        s.getItem('__aiteachme_probe__');
        ok = true;
      }
    } catch (e) {
      ok = false;
    }
    if (!ok) {
      try { Object.defineProperty(window, name, { value: makeStore(), configurable: true }); } catch (e) {}
    }
  });
})();
</script>`;

const ERROR_CAPTURE_SHIM = `<script data-aiteachme-iframe-error-shim>
(function () {
  var buffer = [];
  function emit(errorKind, message) {
    try {
      window.parent.postMessage(
        { __aiteachmeInteractive: true, kind: 'runtime-error', errorKind: errorKind, message: message },
        '*'
      );
    } catch (e) {}
  }
  function post(errorKind, message) {
    message = String(message).slice(0, 1200);
    if (buffer.length < 50) buffer.push([errorKind, message]);
    emit(errorKind, message);
  }
  window.addEventListener('message', function (e) {
    var d = e && e.data;
    if (d && d.__aiteachmeErrorReplayRequest === true) {
      for (var i = 0; i < buffer.length; i++) emit(buffer[i][0], buffer[i][1]);
    }
  });
  window.addEventListener('error', function (e) {
    if (e && e.message) {
      post('error', e.message + (e.filename ? ' (' + e.filename + ':' + (e.lineno || 0) + ')' : ''));
    } else if (e && e.target && (e.target.src || e.target.href)) {
      post('resource', 'Failed to load resource: ' + (e.target.src || e.target.href));
    }
  }, true);
  window.addEventListener('unhandledrejection', function (e) {
    var r = e && e.reason;
    post('unhandledrejection', (r && (r.stack || r.message)) || r || 'unhandled promise rejection');
  });
  try {
    var c = window.console;
    if (c && c.error) {
      var originalConsoleError = c.error;
      c.error = function () {
        try {
          post('console.error', Array.prototype.map.call(arguments, function (a) {
            return (a && a.stack) || String(a);
          }).join(' '));
        } catch (e) {}
        return originalConsoleError.apply(c, arguments);
      };
    }
  } catch (e) {}
})();
</script>`;

const INTERACTIVE_3D_WATCHDOG_SHIM = `<script data-aiteachme-iframe-3d-watchdog>
(function () {
  var watchdogStarted = false;
  function isVisualization3d() {
    try {
      var config = document.getElementById('widget-config');
      if (config && /"type"\\s*:\\s*"visualization3d"/i.test(config.textContent || '')) return true;
      var html = document.documentElement.innerHTML.slice(0, 200000);
      if (/visualization3d/i.test(html)) return true;
      if (/(Loading 3D|正在加载3D|three\\.module|OrbitControls|THREE\\.)/i.test(html) && findLoadingOverlay()) return true;
    } catch (e) {}
    return false;
  }
  function findLoadingOverlay() {
    var candidates = [
      document.getElementById('loading'),
      document.getElementById('loading-overlay'),
      document.querySelector('[data-loading]'),
      document.querySelector('.loading')
    ].filter(Boolean);
    for (var i = 0; i < candidates.length; i++) {
      var text = String(candidates[i].textContent || '');
      if (/3D|Three|场景|加载|Loading/i.test(text)) return candidates[i];
    }
    return candidates[0] || null;
  }
  function showLoadError(message) {
    var loading = findLoadingOverlay();
    if (!loading) return;
    loading.style.display = 'flex';
    loading.style.alignItems = 'center';
    loading.style.justifyContent = 'center';
    loading.style.background = loading.style.background || '#0a0a1a';
    loading.innerHTML = '<div style="max-width:520px;padding:24px;text-align:center;color:#fecaca;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">' +
      '<div style="font-size:15px;font-weight:700;margin-bottom:8px;">3D 场景加载失败</div>' +
      '<div style="font-size:12px;line-height:1.7;color:#cbd5e1;">' + String(message || '请重试生成，或检查浏览器 WebGL/CDN 网络是否可用。').replace(/[<>&]/g, function (ch) {
        return ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : '&amp;';
      }) + '</div>' +
    '</div>';
  }
  function hideStaleLoadingIfCanvasReady() {
    var loading = findLoadingOverlay();
    var canvas = document.querySelector('canvas');
    if (!loading || !canvas) return false;
    var rect = canvas.getBoundingClientRect();
    if (rect.width > 8 && rect.height > 8) {
      loading.style.display = 'none';
      return true;
    }
    return false;
  }
  function start() {
    if (watchdogStarted) return;
    if (!isVisualization3d()) return;
    watchdogStarted = true;
    var attempts = 0;
    var timer = window.setInterval(function () {
      attempts += 1;
      if (hideStaleLoadingIfCanvasReady()) {
        window.clearInterval(timer);
        return;
      }
      if (attempts >= 80) {
        window.clearInterval(timer);
        if (!document.querySelector('canvas')) {
          showLoadError('Three.js 脚本或 WebGL 初始化没有成功完成。');
        }
      }
    }, 250);
    window.addEventListener('error', function (event) {
      var target = event && event.target;
      if (target && (target.src || target.href)) {
        showLoadError('远程 3D 资源加载失败：' + (target.src || target.href));
      } else if (event && event.message) {
        showLoadError(event.message);
      }
    }, true);
    window.addEventListener('unhandledrejection', function (event) {
      var reason = event && event.reason;
      showLoadError((reason && (reason.message || reason.stack)) || reason || '3D 初始化 Promise 失败。');
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
  start();
  [250, 1000, 2500, 5000].forEach(function (delay) {
    window.setTimeout(start, delay);
  });
})();
</script>`;

const INTERACTIVE_3D_SYNTAX_GUARD_SHIM = `<script data-aiteachme-iframe-3d-syntax-guard>
(function () {
  function is3dDocument() {
    try {
      var html = document.documentElement.innerHTML.slice(0, 200000);
      return /visualization3d|Loading 3D|正在加载3D|three\\.module|OrbitControls|THREE\\./i.test(html);
    } catch (e) {
      return false;
    }
  }
  function stripStringsAndComments(source) {
    return String(source || '')
      .replace(/(['"\`])(?:\\\\.|(?!\\1)[\\s\\S])*\\1/g, '""')
      .replace(/\\/\\/.*?$|\\/\\*[\\s\\S]*?\\*\\//gm, '');
  }
  function firstNonAsciiIdentifier() {
    var scripts = Array.prototype.slice.call(document.scripts || []);
    for (var i = 0; i < scripts.length; i++) {
      var type = String(scripts[i].type || '').toLowerCase();
      if (type && !/^(module|text\\/javascript|application\\/javascript|application\\/ecmascript|text\\/ecmascript)$/.test(type)) continue;
      var cleaned = stripStringsAndComments(scripts[i].textContent || '');
      var matches = cleaned.match(/[^\\W\\d]\\w*/gu) || [];
      for (var j = 0; j < matches.length; j++) {
        if (/[^\\x00-\\x7F]/.test(matches[j])) return matches[j];
      }
    }
    return '';
  }
  function showBlocked(identifier) {
    document.documentElement.innerHTML = '<head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#0a0a1a;color:#fecaca;font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}.box{min-height:100%;display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box;text-align:center}.card{max-width:560px}.title{font-weight:700;font-size:16px;margin-bottom:10px}.msg{font-size:13px;line-height:1.8;color:#cbd5e1}</style></head><body><div class="box"><div class="card"><div class="title">3D 场景需要重新生成</div><div class="msg">生成的 JavaScript 中出现未加引号的非英文标识符：<code>' + String(identifier).replace(/[<>&]/g, function (ch) { return ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : '&amp;'; }) + '</code>。请点击改进/重新生成，新的后端校验会拦截这类结果。</div></div></div></body>';
  }
  if (!is3dDocument()) return;
  var identifier = firstNonAsciiIdentifier();
  if (identifier) {
    showBlocked(identifier);
    throw new SyntaxError('Blocked invalid non-ASCII JavaScript identifier: ' + identifier);
  }
})();
</script>`;
const ENABLE_INTERACTIVE_3D_IFRAME_SHIMS = false;

function findHeadOpenMatch(html: string): RegExpExecArray | null {
  const bodyMatch = /<body\b/i.exec(html);
  const searchEnd = bodyMatch?.index ?? Math.min(html.length, 12000);
  return /<head(?:\s[^>]*)?>/i.exec(html.slice(0, searchEnd));
}

function findLastClosingHeadIndex(html: string): number {
  const bodyMatch = /<body\b/i.exec(html);
  const searchEnd = bodyMatch?.index ?? Math.min(html.length, 12000);
  const prefix = html.slice(0, searchEnd);
  const pattern = /<\/head\s*>/gi;
  let lastIndex = -1;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(prefix)) !== null) {
    lastIndex = match.index;
  }
  return lastIndex;
}

function findLastClosingBodyIndex(html: string): number {
  const pattern = /<\/body\s*>/gi;
  let lastIndex = -1;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html)) !== null) {
    lastIndex = match.index;
  }
  return lastIndex;
}

export function patchHtmlForIframe(html: string): string {
  const iframeCss = `<style data-aiteachme-iframe-patch>
  html {
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    scrollbar-gutter: stable;
  }
  body {
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: auto !important;
    box-sizing: border-box !important;
    overscroll-behavior: contain;
  }
  body > :where(#app, .app, main, .main, .layout, .container, .wrapper) {
    max-width: 100% !important;
    max-height: 100% !important;
    min-height: 0 !important;
  }
  body > :where(#app, .app) {
    height: 100% !important;
    overflow: hidden auto !important;
  }
  body > :where(#app, .app) :where(canvas, svg) {
    max-height: 100% !important;
  }
  *, *::before, *::after {
    box-sizing: border-box;
  }
  script, style, template {
    display: none !important;
  }
  body > * {
    max-width: 100%;
  }
  img, svg, canvas, video {
    max-width: 100%;
  }
</style>`;
  const layoutGuardScript = `<script data-aiteachme-iframe-layout-guard>
(function () {
  function setImportant(target, property, value) {
    try {
      target.style.setProperty(property, value, 'important');
    } catch (e) {}
  }
  function applyFrameLayout() {
    try {
      var root = document.documentElement;
      if (root) {
        setImportant(root, 'width', '100%');
        setImportant(root, 'height', '100%');
        setImportant(root, 'min-height', '0');
        setImportant(root, 'max-width', '100%');
        setImportant(root, 'margin', '0');
        setImportant(root, 'padding', '0');
        setImportant(root, 'overflow', 'hidden');
        setImportant(root, 'scrollbar-gutter', 'stable');
      }
      if (document.body) {
        setImportant(document.body, 'width', '100%');
        setImportant(document.body, 'height', '100%');
        setImportant(document.body, 'min-height', '0');
        setImportant(document.body, 'max-width', '100%');
        setImportant(document.body, 'margin', '0');
        setImportant(document.body, 'padding', '0');
        setImportant(document.body, 'overflow', 'auto');
        setImportant(document.body, 'box-sizing', 'border-box');
        setImportant(document.body, 'overscroll-behavior', 'contain');
        var roots = document.body.querySelectorAll(':scope > #app, :scope > .app');
        for (var i = 0; i < roots.length; i += 1) {
          setImportant(roots[i], 'height', '100%');
          setImportant(roots[i], 'max-height', '100%');
          setImportant(roots[i], 'min-height', '0');
          setImportant(roots[i], 'overflow', 'hidden auto');
        }
      }
    } catch (e) {}
  }
  applyFrameLayout();
  window.addEventListener('DOMContentLoaded', applyFrameLayout);
  window.addEventListener('load', applyFrameLayout);
  window.addEventListener('resize', applyFrameLayout);
  window.setTimeout(applyFrameLayout, 60);
  window.setTimeout(applyFrameLayout, 240);
  window.setTimeout(applyFrameLayout, 900);
})();
</script>`;
  // The 3D shims are kept for when visualization3d is re-enabled. While that
  // widget type is disabled, injecting those guards can corrupt pages that
  // contain HTML snippets inside JavaScript strings.
  const threeDInjection = ENABLE_INTERACTIVE_3D_IFRAME_SHIMS
    ? `\n${INTERACTIVE_3D_SYNTAX_GUARD_SHIM}\n${INTERACTIVE_3D_WATCHDOG_SHIM}`
    : "";
  const earlyInjection = `\n${ERROR_CAPTURE_SHIM}\n${STORAGE_SHIM}${threeDInjection}`;
  const lateCss = `\n${iframeCss}`;
  const appendLayoutGuard = (patchedHtml: string) => {
    const closingBodyIndex = findLastClosingBodyIndex(patchedHtml);
    if (closingBodyIndex >= 0) {
      return patchedHtml.slice(0, closingBodyIndex) + `\n${layoutGuardScript}\n` + patchedHtml.slice(closingBodyIndex);
    }
    return `${patchedHtml}\n${layoutGuardScript}`;
  };

  const headWithAttrs = findHeadOpenMatch(html);
  if (headWithAttrs?.index !== undefined) {
    const insertPos = headWithAttrs.index + headWithAttrs[0].length;
    const closingHeadIndex = findLastClosingHeadIndex(html);
    if (closingHeadIndex >= insertPos) {
      return appendLayoutGuard(
        html.slice(0, insertPos) +
          earlyInjection +
          html.slice(insertPos, closingHeadIndex) +
          lateCss +
          html.slice(closingHeadIndex),
      );
    }
    return appendLayoutGuard(html.slice(0, insertPos) + earlyInjection + lateCss + html.slice(insertPos));
  }

  return appendLayoutGuard(earlyInjection + lateCss + html);
}
