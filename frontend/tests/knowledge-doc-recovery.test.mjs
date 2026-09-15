import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import { QueryClient, QueryObserver } from "@tanstack/query-core";
import {
  blockingDocumentReadError,
  documentReadRecoveryDelay,
  isTransientDocumentReadError,
  retryDocumentRead,
} from "../src/components/knowledge-docs/documentReadRecovery.ts";
import { CanceledError } from "axios";
import { apiClient, getApiErrorCode, getApiErrorMessage, markBackendOffline, markBackendOnline } from "../src/api/client.ts";

const httpError = (status, error_code) => Object.assign(new Error(`Request failed with status code ${status}`), {
  response: { status, data: error_code ? { error_code } : "<html>Bad Gateway</html>" },
});

test("temporary read failures retain progress, permanent errors remain visible", () => {
  for (const status of [408, 429, 500, 502, 503, 504]) {
    const error = httpError(status);
    assert.equal(isTransientDocumentReadError(error), true);
    assert.equal(blockingDocumentReadError([error], true), null);
    assert.equal(blockingDocumentReadError([error], false), error);
  }
  for (const error of [httpError(401), httpError(403), httpError(404), httpError(409),
    httpError(503, "PUBLISHED_DOCUMENT_STRUCTURE_INVALID"), new Error("Invalid chapter response")]) {
    assert.equal(isTransientDocumentReadError(error), false);
    assert.equal(blockingDocumentReadError([httpError(502), error], true), error);
    assert.equal(retryDocumentRead(0, error), false);
  }
  assert.equal(isTransientDocumentReadError({ code: "ERR_NETWORK" }), true);
  assert.equal(isTransientDocumentReadError({ code: "ERR_CANCELED" }), false);
});

test("gateway HTML errors use Chinese text while business errors keep their explanation", () => {
  assert.match(getApiErrorMessage(httpError(502)), /后台任务可能仍在执行/);
  const error = httpError(503, "PUBLISHED_DOCUMENT_STRUCTURE_INVALID");
  error.response.data.message = "已发布文档结构异常，请重新构建。";
  assert.equal(getApiErrorMessage(error), error.response.data.message);
});

test("requests stopped by an outage remain recoverable after the backend comes online", async () => {
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const request = apiClient({ url: "/offline-read-test", adapter: config => new Promise((_resolve, reject) => {
    config.signal.addEventListener("abort", () => reject(new CanceledError("canceled", config)), { once: true });
    started();
  }) });
  await ready;
  markBackendOffline("test");
  markBackendOnline();
  await assert.rejects(request, error => isTransientDocumentReadError(error));
});

test("explicit caller cancellation is not treated as an outage to retry", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(apiClient({ url: "/cancelled-read-test", signal: controller.signal }),
    error => error.code === "ERR_CANCELED" && !isTransientDocumentReadError(error));
});

// Execute the hook's actual recovery effect and refresh callback in isolation.
// QueryObserver supplies real cache/retry behavior; only HTTP, timers and hook
// state setters are replaced. No browser or additional renderer dependency.
const hookPath = new URL("../src/components/knowledge-docs/hooks/useDocMarkdown.ts", import.meta.url);
const source = ts.createSourceFile(hookPath.pathname, fs.readFileSync(hookPath, "utf8"), ts.ScriptTarget.Latest, true);
function find(predicate, sourceFile = source) {
  let found;
  function visit(node) { if (!found && predicate(node)) found = node; if (!found) ts.forEachChild(node, visit); }
  visit(sourceFile);
  assert.ok(found, "Hook recovery source must be present");
  return found;
}
const refreshCallback = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "refreshDocument").initializer.arguments[0];
const recoveryEffect = find(node => ts.isCallExpression(node) && node.expression.getText(source) === "useEffect" &&
  node.arguments[0]?.getText(source).includes("setReadRecoveryPending(true)")).arguments[0];
function evaluate(node, scope) {
  const code = ts.transpileModule(`(${node.getText(node.getSourceFile())})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
  }).outputText;
  const documentScope = {};
  return vm.runInNewContext(code, { documentScope, documentScopeRef: { current: documentScope }, ...scope });
}

const pagePath = new URL("../src/pages/KnowledgeDocsPage.tsx", import.meta.url);
const pageSource = ts.createSourceFile(pagePath.pathname, fs.readFileSync(pagePath, "utf8"),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const errorPanelActions = [];
function collectErrorPanelActions(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(pageSource) === "DocLoadErrorState") {
    const action = node.attributes.properties.find(property => property.name?.getText(pageSource) === "secondaryAction");
    if (action) errorPanelActions.push(action.initializer.expression);
  }
  ts.forEachChild(node, collectErrorPanelActions);
}
collectErrorPanelActions(pageSource);
const rebuildCallback = find(node => ts.isVariableDeclaration(node) &&
  node.name.getText(pageSource) === "handleFailedBuildRetry", pageSource).initializer.arguments[0];

test("both document error panels offer a working rebuild action for structural corruption", () => {
  assert.equal(errorPanelActions.length, 2);
  for (const actionExpression of errorPanelActions) {
    for (const confirmedPlanId of ["plan-1", null]) {
      let rebuilds = 0;
      const navigations = [];
      const handleFailedBuildRetry = evaluate(rebuildCallback, {
        courseId: "course-test", failedBuildConfirmedPlanId: confirmedPlanId,
        retryKnowledgeBuild: () => rebuilds++, navigate: path => navigations.push(path),
        buildCoursePath: (courseId, page) => `/courses/${courseId}/${page}`,
      });
      const action = evaluate(actionExpression, {
        isBuildFailure: false,
        documentLoadError: httpError(503, "PUBLISHED_DOCUMENT_STRUCTURE_INVALID"),
        getApiErrorCode, failedBuildConfirmedPlanId: confirmedPlanId,
        handleFailedBuildRetry, isRetryKnowledgeBuildPending: false,
      });
      assert.ok(action, "A completed build with corrupt publication must allow rebuilding");
      assert.equal(action.label, confirmedPlanId ? "重新构建" : "返回方案重新构建");
      action.onClick();
      assert.equal(rebuilds, confirmedPlanId ? 1 : 0);
      assert.deepEqual(navigations, confirmedPlanId ? [] : ["/courses/course-test/build"]);
    }
  }
});

test("temporary reads do not offer a rebuild unless the build itself has failed", () => {
  for (const actionExpression of errorPanelActions) {
    for (const documentLoadError of [httpError(502), httpError(503), { code: "ERR_NETWORK" }]) {
      const scope = {
        isBuildFailure: false, documentLoadError, getApiErrorCode,
        failedBuildConfirmedPlanId: "plan-1", handleFailedBuildRetry() {},
        isRetryKnowledgeBuildPending: true,
      };
      assert.equal(evaluate(actionExpression, scope), undefined);
      const failedAction = evaluate(actionExpression, { ...scope, isBuildFailure: true });
      assert.equal(failedAction.label, "重新构建");
      assert.equal(failedAction.isPending, true);
    }
  }
});

test("publication switches retry the manifest but never retry a chunk under its stale ID", () => {
  const options = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "publicationManifestQuery").initializer.arguments[0];
  const retry = options.properties.find(property => property.name?.getText(source) === "retry").initializer;
  const retryManifest = evaluate(retry, { getHttpStatus: error => error.response.status, retryDocumentRead });
  assert.equal(retryManifest(0, httpError(409)), true);
  assert.equal(retryManifest(2, httpError(409)), false);
  assert.equal(retryDocumentRead(0, httpError(409)), false);
});

test("a genuine failed build remains a failure even when a read is temporarily unavailable", () => {
  const failureState = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "showDocBuildFailureState").initializer;
  const error = blockingDocumentReadError([httpError(502)], true);
  assert.equal(evaluate(failureState, {
    documentLoadError: error, hasLiveDocMarkdown: false, hasDraftDocMarkdown: false,
    showDocLoadingState: false, isBuildFailure: true,
  }), true);
});

test("a requested build retains its waiting state when the first metadata response is missing", () => {
  const waitingState = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "isWaitingForRequestedBuild").initializer;
  const scope = { isRequestedBuildReady: false, isBuildFailure: false, draftAvailable: false,
    isBuildActive: false, isBuildReadyStatus: false, targetRequestedAtMs: 1234,
    buildStatus: null, requestedAtMs: 1234 };
  assert.equal(evaluate(waitingState, scope), true);
  assert.equal(evaluate(waitingState, { ...scope, targetRequestedAtMs: null, requestedAtMs: null }), false);
  assert.equal(evaluate(waitingState, { ...scope, isBuildFailure: true }), false);
});

test("an older ready document cannot finish a newly requested build while metadata is unavailable", () => {
  const targetExpression = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "targetRequestedAtMs" &&
    node.parent.parent.parent.getText(source).includes("fallbackRequestedBuildReady")).initializer;
  const target = evaluate(targetExpression, { buildStatus: null, requestedAtMs: 1234, buildRequestedAtMs: null });
  assert.equal(target, 1234);
  const readyExpression = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "isRequestedBuildReady").initializer;
  assert.equal(evaluate(readyExpression, {
    targetRequestedAtMs: target, fallbackRequestedBuildReady: false,
    runtimeQuery: { data: { docs_ready: true } }, isRuntimeDocumentReady: true,
  }), false);
});

test("fresh metadata failure status takes precedence over an unavailable runtime's stale running status", () => {
  const buildExpression = find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === "buildMeta").initializer;
  const failed = { status: "failed", error_message: "generation failed" };
  const runtime = { docgen: { status: "running" } };
  assert.equal(evaluate(buildExpression, { runtimeQuery: { isError: true, data: runtime },
    docMarkdownQuery: { data: { build: failed } } }), failed);
  assert.equal(evaluate(buildExpression, { runtimeQuery: { isError: false, data: runtime },
    docMarkdownQuery: { data: { build: failed } } }), runtime.docgen);
});

test("a manifest 502 recovers even when metadata polling has already recovered", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: retryDocumentRead, retryDelay: 0, gcTime: Infinity } } });
  let available = false;
  let manifestCalls = 0;
  const metadata = new QueryObserver(client, { queryKey: ["metadata"], queryFn: async () => ({ exists: false, build: { status: "running" } }) });
  const manifest = new QueryObserver(client, { queryKey: ["manifest"], queryFn: async () => {
    manifestCalls++;
    if (!available) throw httpError(502);
    return { exists: false, publication_id: null, chunks: [] };
  } });
  try {
    await Promise.all([metadata.refetch(), manifest.refetch()]);
    assert.equal(manifestCalls, 3);
    assert.equal(manifest.getCurrentResult().isError, true);
    available = true;
    await metadata.refetch();
    const readError = manifest.getCurrentResult().error;
    assert.equal(blockingDocumentReadError([readError], true), null);

    const refresh = evaluate(refreshCallback, {
      publicationChunksRef: { current: [] }, publicationError: null,
      docMarkdownQuery: metadata, draftAvailable: false,
      publicationMountedRef: { current: true },
      refetchPublicationManifest: manifest.refetch.bind(manifest),
      activePublicationIdRef: { current: null }, publicationManifestRef: {},
    });
    let timer, pending, attempt = 0, reading;
    const cleanup = evaluate(recoveryEffect, {
      courseId: "course-test", readError, recoverableReadError: true,
      readRecoveryPending: false, recoveryDelay: documentReadRecoveryDelay(0),
      setReadRecoveryAttempt: update => { attempt = update(attempt); },
      setReadRecoveryPending: value => { pending = value; },
      publicationMountedRef: { current: true },
      refreshDocument: () => { reading = refresh(); return reading; },
      window: { setTimeout: (callback, delay) => { timer = { callback, delay }; return 1; }, clearTimeout() {} },
    })();
    assert.equal(timer.delay, 2000);
    timer.callback();
    assert.equal(pending, true);
    await reading;
    assert.equal(attempt, 1);
    assert.equal(manifestCalls, 4);
    assert.equal(manifest.getCurrentResult().error, null);
    cleanup();
  } finally { client.clear(); }
});

test("recovery retries a failed next chunk without clearing already readable chapters", async () => {
  const chunks = { current: [{ markdown: "# Existing chapter" }] };
  const manifest = { publication_id: "pub-1", chunks: [{}, {}] };
  const attempts = [];
  const refresh = evaluate(refreshCallback, {
    publicationChunksRef: chunks, publicationError: httpError(502),
    docMarkdownQuery: { refetch: async () => ({ isError: false }) }, draftAvailable: false,
    publicationMountedRef: { current: true },
    refetchPublicationManifest: async () => ({ isError: false, data: manifest }),
    activePublicationIdRef: { current: "pub-1" }, publicationManifestRef: {},
    resetPublicationChunks: () => { throw new Error("Existing content must remain readable"); },
    ensureChunkIndexLoaded: async index => { attempts.push(index); return true; },
  });
  await refresh();
  assert.deepEqual(attempts, [1]);
  assert.equal(chunks.current[0].markdown, "# Existing chapter");
});

test("automatic recovery is bounded, and switching courses cancels the queued retry", () => {
  assert.deepEqual(Array.from({ length: 7 }, (_, n) => documentReadRecoveryDelay(n)), [2000, 4000, 8000, 16000, 30000, null, null]);
  let scheduled = 0, cleared = 0;
  const scope = {
    courseId: "course-test", readError: httpError(502), recoverableReadError: true,
    readRecoveryPending: false, recoveryDelay: null,
    window: { setTimeout: () => ++scheduled, clearTimeout: () => cleared++ },
  };
  assert.equal(evaluate(recoveryEffect, scope)(), undefined);
  assert.equal(scheduled, 0);
  const cleanup = evaluate(recoveryEffect, { ...scope, recoveryDelay: 2000 })();
  cleanup();
  assert.equal(scheduled, 1);
  assert.equal(cleared, 1);
  assert.equal(evaluate(recoveryEffect, { ...scope, recoveryDelay: 2000, readRecoveryPending: true })(), undefined);
  assert.equal(scheduled, 1);
});

test("an old refresh cannot read chunks or replace the manifest after switching courses", async () => {
  const documentScope = { courseId: "course-a", requestedAt: null };
  const documentScopeRef = { current: documentScope };
  const manifest = { publication_id: "pub-a", chunks: [{}] };
  let completeManifest;
  const response = new Promise(resolve => { completeManifest = resolve; });
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const currentManifest = { current: { publication_id: "pub-b" } };
  const refresh = evaluate(refreshCallback, {
    documentScope, documentScopeRef,
    publicationChunksRef: { current: [] }, publicationError: null,
    docMarkdownQuery: { refetch: async () => ({ isError: false }) }, draftAvailable: false,
    publicationMountedRef: { current: true },
    refetchPublicationManifest: () => { started(); return response; },
    activePublicationIdRef: { current: "pub-b" }, publicationManifestRef: currentManifest,
    resetPublicationChunks: () => assert.fail("Old refresh reset the new course"),
    ensureChunkIndexLoaded: () => assert.fail("Old refresh requested a new course's chunks"),
  });
  const pending = refresh();
  await ready;
  documentScopeRef.current = { courseId: "course-b", requestedAt: null };
  completeManifest({ isError: false, data: manifest });
  await pending;
  assert.equal(currentManifest.current.publication_id, "pub-b");
});
