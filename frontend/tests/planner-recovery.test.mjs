import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";
import { normalizePlannerDiagnosticAnswer, normalizePlannerDiagnosticAnswers } from "../src/components/build-plan/plannerDiagnosis.ts";

// Execute the page's real persistence helpers and effects with synthetic data.
// Only HTTP, hook state and timers are replaced; no model or server is called.
const pagePath = new URL("../src/pages/BuildPlanPage.tsx", import.meta.url);
const source = ts.createSourceFile(pagePath.pathname, fs.readFileSync(pagePath, "utf8"),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function find(predicate, root = source) {
  let found;
  function visit(node) {
    if (!found && predicate(node)) found = node;
    if (!found) ts.forEachChild(node, visit);
  }
  visit(root);
  assert.ok(found, "Planner recovery source must be present");
  return found;
}
function evaluate(node, scope = {}) {
  const code = ts.transpileModule(`const result = (${node.getText(source)});`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
  }).outputText;
  return new Function(...Object.keys(scope), `${code}; return result;`)(...Object.values(scope));
}
const effect = text => find(node => ts.isCallExpression(node)
  && node.expression.getText(source) === "useEffect" && node.arguments[0]?.getText(source).includes(text)).arguments[0];
const restoreEffect = effect("const persisted = readPersistedPlannerState(");
const persistEffect = effect("persistPlannerState(");
const pollEffect = effect("async function refreshLatestPlannerSession()");
const autoStartEffect = effect("autoStartFiredRef.current = true");
const declaration = name => find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === name).initializer;
const local = new Map(), session = new Map(), writes = [];
const store = map => ({
  getItem: key => map.get(key) ?? null,
  setItem: (key, value) => { map.set(key, String(value)); writes.push({ key, value: String(value) }); },
});
const windowStub = { localStorage: store(local), sessionStorage: store(session) };
const helperNames = new Set([
  "storageKey", "STORAGE_PREFIX", "PLANNER_STATE_VERSION", "LEGACY_WELCOME_MESSAGE_CONTENT", "TRANSIENT_PLANNER_ERROR_SNIPPETS",
  "readPersistedPlannerState", "persistPlannerState", "sanitizePlannerMessages", "usablePlannerPlan", "hasRenderablePlannerDraft",
  "hasUsablePlannerPlan", "plannerChapters", "plannerView", "plannerDiagnose", "hasPlannerDiagnosis", "planSessionId",
  "isInternalPlannerDiagnosisPrompt", "createPlannerDiagnosisGate", "planStatus", "createInitialMessages", "plannerSessionStatus",
  "isPlannerServerStatusPending", "isPlannerServerStatusTerminal", "appendPlannerTerminalMessageIfNeeded", "plannerTerminalMessage",
  "createMessage", "nextMessageId", "messageCounter", "buildPlannerMessagesFromSession",
  "isPlannerDiagnoseResolved", "plannerDiagnoseStatus", "plannerDiagnoseAnswers",
]);
const selected = source.statements.filter(node => ts.isFunctionDeclaration(node)
  ? helperNames.has(node.name?.text)
  : ts.isVariableStatement(node) && node.declarationList.declarations.some(item => helperNames.has(item.name.getText(source))));
const helperCode = ts.transpileModule(selected.map(node => node.getText(source)).join("\n"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;
const helpers = new Function("window", "logPlannerDebug", "normalizePlannerDiagnosticAnswer", "normalizePlannerDiagnosticAnswers",
  `${helperCode}; return {${[...helperNames].join(",")}};`)(windowStub, () => {}, normalizePlannerDiagnosticAnswer, normalizePlannerDiagnosticAnswers);
const plan = { chapters: [{ title: "Synthetic chapter" }], status: "draft", planner_session_id: "session-a" };
const cachedState = marker => ({
  messages: [{ id: "m1", role: "user", content: `${marker}_MESSAGE` },
    { id: "m2", role: "assistant", content: `${marker}_PLAN`, plan }],
  plannerSessionId: "session-a", currentPlan: plan, inputValue: `${marker}_DRAFT`, plannerNeedsRefresh: false, diagnosisGate: null,
});
function restoreScope(userId, extra = {}) {
  const rendered = {};
  const scope = {
    ...helpers, window: windowStub, courseId: "course-a", plannerUserId: userId,
    plannerScope: userId ? helpers.storageKey(userId, "course-a") : null, navState: null,
    hydratedPlannerScope: null, localInteractionPlannerScopeRef: { current: null },
    autoStartFiredRef: { current: false }, logPlannerDebug() {},
    apiClient: async () => ({ data: null }), ...extra,
  };
  for (const name of ["Messages", "PlannerSessionId", "CurrentPlan", "PlannerServerStatus", "InputValue", "PlannerNeedsRefresh", "DiagnosisGate", "HasAutoUploaded"]) {
    scope[`set${name}`] = value => { rendered[name] = typeof value === "function" ? value(rendered[name]) : value; };
  }
  scope.setHydratedPlannerScope = value => { scope.pendingHydratedPlannerScope = value; };
  return { scope, rendered };
}
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };

test("same account and fixed local identity restore their own plan and unsent draft", () => {
  for (const userId of ["account-a", "local"]) {
    helpers.persistPlannerState(userId, "course-a", cachedState(userId));
    const { scope, rendered } = restoreScope(userId, { apiClient() { assert.fail("Cache hit must retain local draft"); } });
    evaluate(restoreEffect, scope)();
    assert.equal(rendered.InputValue, `${userId}_DRAFT`);
    assert.equal(rendered.Messages[0].content, `${userId}_MESSAGE`);
    assert.deepEqual(rendered.CurrentPlan, plan);
  }
});

test("another account or guest never restores the previous account's messages", async () => {
  helpers.persistPlannerState("account-a", "course-a", cachedState("ACCOUNT_A"));
  for (const userId of ["account-b", "guest-b"]) {
    let calls = 0;
    const { scope, rendered } = restoreScope(userId, { apiClient: async () => { calls++; throw new Error("Synthetic 404"); } });
    evaluate(restoreEffect, scope)();
    await flush();
    assert.equal(calls, 1);
    assert.deepEqual(rendered.Messages, []);
    assert.equal(rendered.CurrentPlan, null);
    assert.equal(rendered.InputValue, "");
  }
});

test("unknown identity neither reads nor writes planner history, including unowned legacy keys", () => {
  const legacy = JSON.stringify({ ...cachedState("LEGACY"), version: helpers.PLANNER_STATE_VERSION });
  local.set(`${helpers.STORAGE_PREFIX}:course-a`, legacy);
  session.set(`${helpers.STORAGE_PREFIX}:course-a`, legacy);
  assert.equal(helpers.readPersistedPlannerState(null, "course-a"), null);
  assert.equal(helpers.readPersistedPlannerState("new-account", "course-a"), null);
  const before = writes.length;
  helpers.persistPlannerState(null, "course-a", cachedState("UNKNOWN"));
  const { scope, rendered } = restoreScope(null, { apiClient() { assert.fail("Identity must be known before restoring"); } });
  evaluate(restoreEffect, scope)();
  evaluate(persistEffect, { ...scope, ...cachedState("UNKNOWN") })();
  assert.deepEqual(rendered, {});
  assert.equal(writes.length, before);
  assert.notEqual(helpers.storageKey("a:b", "c"), helpers.storageKey("a", "b:c"));
});

test("identity changes remount page state before any new account cache write", () => {
  const wrapper = find(node => ts.isFunctionDeclaration(node) && node.name?.text === "BuildPlanPage");
  const child = find(node => ts.isJsxSelfClosingElement(node) && node.tagName.getText(source) === "BuildPlanPageContent", wrapper);
  const key = child.attributes.properties.find(property => property.name?.getText(source) === "key").initializer.expression;
  const pageKey = (userId, courseId = "course-a") => evaluate(key, { plannerUserId: userId, courseId, storageKey: helpers.storageKey });
  assert.notEqual(pageKey("account-a"), pageKey("account-b"));
  assert.notEqual(pageKey(null), pageKey("account-b"));
  assert.notEqual(pageKey("account-a"), pageKey("account-a", "course-b"));
  assert.equal(pageKey("local"), pageKey("local"));
  helpers.persistPlannerState("account-a", "course-a", cachedState("ACCOUNT_A"));
  helpers.persistPlannerState("account-b", "course-a", cachedState("ACCOUNT_B"));
  writes.length = 0;
  // A new keyed child starts with empty hook state, even if B has a cache hit.
  const { scope, rendered } = restoreScope("account-b");
  evaluate(restoreEffect, scope)();
  evaluate(persistEffect, { ...scope, ...cachedState(""), messages: [], currentPlan: null, plannerSessionId: null, inputValue: "" })();
  evaluate(persistEffect, { ...scope, messages: rendered.Messages, currentPlan: rendered.CurrentPlan,
    plannerSessionId: rendered.PlannerSessionId, inputValue: rendered.InputValue,
    plannerNeedsRefresh: rendered.PlannerNeedsRefresh, diagnosisGate: rendered.DiagnosisGate,
    hydratedPlannerScope: scope.pendingHydratedPlannerScope })();
  assert.ok(writes.length > 0);
  assert.ok(writes.every(write => !write.value.includes("ACCOUNT_A")));
  assert.equal(helpers.readPersistedPlannerState("account-b", "course-a").inputValue, "ACCOUNT_B_DRAFT");
});

test("StrictMode hydration never persists initial empty state before restored state reaches a new render", () => {
  for (const [userId, courseId, marker] of [
    ["account-a", "course-a", "SAME_ACCOUNT"],
    ["account-b", "course-a", "SWITCHED_ACCOUNT"],
    ["account-a", "course-b", "SWITCHED_COURSE"],
  ]) {
    helpers.persistPlannerState(userId, courseId, cachedState(marker));
    writes.length = 0;
    const plannerScope = helpers.storageKey(userId, courseId);
    const { scope } = restoreScope(userId, { courseId, plannerScope });
    const state = { messages: [], plannerSessionId: null, currentPlan: null, plannerServerStatus: null,
      inputValue: "", plannerNeedsRefresh: false, diagnosisGate: null, hasAutoUploaded: false, hydratedPlannerScope: null };
    const updates = [];
    // React setters queue updates; effect closures retain the initial render's values.
    for (const field of Object.keys(state)) {
      scope[`set${field[0].toUpperCase()}${field.slice(1)}`] = value => updates.push({ field, value });
    }
    const render = () => ({
      restore: evaluate(restoreEffect, { ...scope, ...state }),
      persist: evaluate(persistEffect, { ...scope, ...state }),
    });
    const firstRender = render();
    const cleanup = firstRender.restore();
    firstRender.persist();
    assert.equal(writes.length, 0);
    cleanup?.();
    // StrictMode repeats setup before applying queued hydration state.
    const replayRender = render();
    replayRender.restore();
    replayRender.persist();
    assert.equal(writes.length, 0, `${marker}: initial closures must not overwrite storage`);
    assert.equal(helpers.readPersistedPlannerState(userId, courseId).inputValue, `${marker}_DRAFT`);
    for (const { field, value } of updates) state[field] = typeof value === "function" ? value(state[field]) : value;
    render().persist();
    assert.ok(writes.length > 0);
    assert.ok(writes.every(write => JSON.parse(write.value).inputValue === `${marker}_DRAFT`));
    assert.equal(state.inputValue, `${marker}_DRAFT`);
    assert.equal(state.messages[0].content, `${marker}_MESSAGE`);
    assert.deepEqual(state.currentPlan, plan);
  }
});

test("late restore cannot overwrite a newer local interaction", async () => {
  let config, resolve;
  const { scope, rendered } = restoreScope("restore-only", { apiClient: request => { config = request; return new Promise(done => { resolve = done; }); } });
  const cleanup = evaluate(restoreEffect, scope)();
  scope.localInteractionPlannerScopeRef.current = scope.plannerScope;
  resolve({ data: null });
  await flush();
  assert.deepEqual(rendered, {});
  cleanup();
  assert.equal(config.signal.aborted, true);
});

test("restore cleanup aborts its request and ignores a late response", async () => {
  let config, resolve;
  const { scope, rendered } = restoreScope("restore-only", { apiClient: request => { config = request; return new Promise(done => { resolve = done; }); } });
  const cleanup = evaluate(restoreEffect, scope)();
  cleanup();
  assert.equal(config.signal.aborted, true);
  resolve({ data: null });
  await flush();
  assert.deepEqual(rendered, {});
});

test("delayed identity waits before autoStart and starts only once after it resolves", () => {
  let started = 0;
  const scope = {
    navState: { autoStart: true, initialPrompt: "Synthetic goal" }, courseId: "course-a", plannerScope: null,
    autoStartFiredRef: { current: false }, plannerStreamInFlightRef: { current: false }, plannerSessionId: null,
    plannerStreaming: false,
    // Stop immediately after the real one-shot guard; no SSE/model is called.
    markPlannerLocalInteraction() { started++; throw new Error("synthetic start boundary"); },
  };
  evaluate(autoStartEffect, scope)();
  assert.equal(started, 0);
  scope.plannerScope = helpers.storageKey("account-c", "course-a");
  assert.throws(() => evaluate(autoStartEffect, scope)(), /synthetic start boundary/);
  evaluate(autoStartEffect, scope)();
  assert.equal(started, 1);
  for (const plannerAuthError of [false, true]) {
    const placeholder = evaluate(declaration("inputPlaceholder"), { plannerScope: null, plannerAuthError });
    assert.match(placeholder, plannerAuthError ? /账户加载失败.*重试/ : /正在加载账户/);
  }
});

test("StrictMode effect replay preserves autoStart stream; real unmount aborts it", async () => {
  const controller = new AbortController();
  const setup = evaluate(effect("plannerPageMountedRef.current = true"), {
    plannerPageMountedRef: { current: false }, plannerAbortControllerRef: { current: controller },
  });
  const replayCleanup = setup();
  replayCleanup();
  const unmount = setup();
  await flush();
  assert.equal(controller.signal.aborted, false);
  unmount();
  await flush();
  assert.equal(controller.signal.aborted, true);
});

function pollingScope() {
  const timers = new Map(), requests = [], rendered = {}, invalidations = [];
  let timerId = 0;
  const scope = {
    ...helpers, courseId: "course-a", plannerSessionId: "poll-session", plannerStreaming: false, plannerServerStatus: "planning",
    window: { setTimeout(callback, delay) { assert.equal(delay, 2500); timers.set(++timerId, callback); return timerId; }, clearTimeout(id) { timers.delete(id); } },
    apiClient: config => new Promise((resolve, reject) => requests.push({ config, resolve, reject })),
    queryClient: { invalidateQueries: value => { invalidations.push(value); } },
    logPlannerDebug() {}, getApiErrorMessage: () => "synthetic error",
  };
  for (const name of ["PlannerServerStatus", "CurrentPlan", "PlannerNeedsRefresh", "DiagnosisGate", "Messages"]) {
    scope[`set${name}`] = value => { rendered[name] = typeof value === "function" ? value(rendered[name]) : value; };
  }
  return { scope, timers, requests, rendered, invalidations };
}

test("slow planner polls never overlap, and unmount aborts and ignores the pending response", async () => {
  const { scope, timers, requests, rendered } = pollingScope();
  const cleanup = evaluate(pollEffect, scope)();
  assert.equal(requests.length, 1);
  assert.equal(timers.size, 0, "No next timer exists while HTTP is in flight");
  requests[0].resolve({ data: { session_id: "poll-session", status: "planning", turns: [] } });
  await flush();
  assert.equal(timers.size, 1);
  const [id, tick] = [...timers][0]; timers.delete(id); tick();
  assert.equal(requests.length, 2);
  assert.equal(timers.size, 0);
  const before = { ...rendered };
  cleanup();
  assert.equal(requests[1].config.signal.aborted, true);
  requests[1].resolve({ data: { session_id: "poll-session", status: "failed", turns: [] } });
  await flush();
  assert.deepEqual(rendered, before);
  assert.equal(timers.size, 0);
});

test("planner poll retries after a settled failure and cleanup clears the next timer", async () => {
  const { scope, timers, requests } = pollingScope();
  const cleanup = evaluate(pollEffect, scope)();
  requests[0].reject(new Error("Synthetic timeout"));
  await flush();
  assert.equal(timers.size, 1);
  cleanup();
  assert.equal(timers.size, 0);
});

test("every terminal planner state stops polling before React effect cleanup", async () => {
  for (const status of ["draft", "failed", "cancelled"]) {
    const { scope, timers, requests, rendered, invalidations } = pollingScope();
    const cleanup = evaluate(pollEffect, scope)();
    requests[0].resolve({ data: { session_id: "poll-session", status, turns: [], latest_plan: status === "draft" ? plan : null } });
    await flush();
    assert.equal(rendered.PlannerServerStatus, status);
    assert.equal(timers.size, 0);
    assert.equal(invalidations.length, 1);
    if (status === "draft") assert.deepEqual(rendered.CurrentPlan, plan);
    if (status !== "draft") assert.match(rendered.Messages[0].content, status === "failed" ? /失败/ : /中断/);
    cleanup();
  }
});
