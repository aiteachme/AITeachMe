import assert from "node:assert/strict";
import test from "node:test";

class BrowserWindowStub extends EventTarget {
  location = {
    search: "",
    protocol: "http:",
    hostname: "localhost",
    origin: "http://localhost",
  };

  setTimeout(handler, delay) {
    return globalThis.setTimeout(handler, delay);
  }

  clearTimeout(handle) {
    globalThis.clearTimeout(handle);
  }
}

const browserWindow = new BrowserWindowStub();
const storage = new Map();
globalThis.window = browserWindow;
globalThis.localStorage = {
  getItem(key) {
    return storage.get(String(key)) ?? null;
  },
  setItem(key, value) {
    storage.set(String(key), String(value));
  },
  removeItem(key) {
    storage.delete(String(key));
  },
};

const {
  API_AUTH_CHANGED_EVENT,
  BACKEND_OFFLINE_EVENT,
  abortActiveApiRequests,
  getApiAuthGeneration,
  isBackendOffline,
  markBackendOnline,
  notifyApiAuthChanged,
  openAuthenticatedSse,
  reportBackendConnectionIssue,
  runTrackedApiFetch,
} = await import("../src/api/client.ts");

const encoder = new TextEncoder();

function delay(ms) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

function withTimeout(promise, timeoutMs = 2_000) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = globalThis.setTimeout(() => reject(new Error(`Timed out after ${timeoutMs}ms`)), timeoutMs);
    }),
  ]).finally(() => globalThis.clearTimeout(timer));
}

function sseResponse(body) {
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}

function failingSseResponse() {
  return sseResponse(new ReadableStream({
    start(controller) {
      controller.error(new TypeError("Failed to fetch"));
    },
  }));
}

function doneSseResponse() {
  return sseResponse(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode("event: done\ndata: {\"status\":\"completed\"}\n\n"));
      controller.close();
    },
  }));
}

function pendingSseResponse(signal) {
  return sseResponse(new ReadableStream({
    start(controller) {
      const abort = () => controller.error(new DOMException("Aborted", "AbortError"));
      if (signal?.aborted) {
        abort();
      } else {
        signal?.addEventListener("abort", abort, { once: true });
      }
    },
  }));
}

function waitForDone(stream) {
  return new Promise((resolve) => {
    stream.addEventListener("done", (event) => {
      stream.close();
      resolve(event);
    }, { once: true });
  });
}

test("isolated SSE resets probe health and reconnect without leaking auth in the URL", async (t) => {
  abortActiveApiRequests();
  markBackendOnline();
  storage.clear();
  storage.set("token", "test-access-token");

  const originalFetch = globalThis.fetch;
  let streamRequests = 0;
  let healthRequests = 0;
  let offlineEvents = 0;
  let firstStreamRequest;
  const onOffline = () => {
    offlineEvents += 1;
  };
  browserWindow.addEventListener(BACKEND_OFFLINE_EVENT, onOffline);

  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    if (url.endsWith("/api/health")) {
      healthRequests += 1;
      return new Response(null, { status: 200 });
    }
    streamRequests += 1;
    firstStreamRequest ??= { url, init };
    return streamRequests === 1 ? failingSseResponse() : doneSseResponse();
  };

  const stream = openAuthenticatedSse("/api/v1/courses/course-1/knowledge/build/stream", {
    maxReconnectAttempts: 1,
    reconnectDelayMs: 250,
  });
  stream.onerror = () => {
    void reportBackendConnectionIssue("test_stream_error");
  };
  t.after(() => {
    stream.close();
    abortActiveApiRequests();
    markBackendOnline();
    browserWindow.removeEventListener(BACKEND_OFFLINE_EVENT, onOffline);
    globalThis.fetch = originalFetch;
  });

  await withTimeout(waitForDone(stream));

  assert.equal(streamRequests, 2);
  assert.equal(healthRequests, 1);
  assert.equal(offlineEvents, 0);
  assert.equal(isBackendOffline(), false);
  assert.equal(firstStreamRequest.url.includes("test-access-token"), false);
  assert.equal(firstStreamRequest.init.credentials, "include");
  assert.equal(firstStreamRequest.init.headers.get("Authorization"), "Bearer test-access-token");
  assert.match(firstStreamRequest.init.headers.get("X-Device-Key"), /^dk_[A-Za-z0-9-]+$/);
});

test("confirmed backend outages pause SSE and resume online without consuming retries", async (t) => {
  abortActiveApiRequests();
  markBackendOnline();
  storage.clear();

  const originalFetch = globalThis.fetch;
  let streamRequests = 0;
  let healthRequests = 0;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/api/health")) {
      healthRequests += 1;
      return new Response(null, { status: 503 });
    }
    streamRequests += 1;
    return streamRequests === 1 ? failingSseResponse() : doneSseResponse();
  };

  const offline = new Promise((resolve) => {
    browserWindow.addEventListener(BACKEND_OFFLINE_EVENT, resolve, { once: true });
  });
  const stream = openAuthenticatedSse("/api/v1/courses/course-2/exams/42/stream", {
    maxReconnectAttempts: 0,
    reconnectDelayMs: 250,
  });
  t.after(() => {
    stream.close();
    abortActiveApiRequests();
    markBackendOnline();
    globalThis.fetch = originalFetch;
  });

  await withTimeout(offline);
  assert.equal(isBackendOffline(), true);
  assert.equal(healthRequests, 1);
  await delay(320);
  assert.equal(streamRequests, 1, "the subscription must remain paused while offline");

  const done = waitForDone(stream);
  markBackendOnline();
  await withTimeout(done);

  assert.equal(streamRequests, 2);
  assert.equal(isBackendOffline(), false);
});

test("explicit abort permanently closes active SSE subscriptions", async (t) => {
  abortActiveApiRequests();
  markBackendOnline();
  storage.clear();

  const originalFetch = globalThis.fetch;
  let streamRequests = 0;
  globalThis.fetch = async (_input, init = {}) => {
    streamRequests += 1;
    return pendingSseResponse(init.signal);
  };

  const stream = openAuthenticatedSse("/api/v1/courses/course-3/exams/43/stream", {
    maxReconnectAttempts: 3,
    reconnectDelayMs: 250,
  });
  t.after(() => {
    stream.close();
    abortActiveApiRequests();
    markBackendOnline();
    globalThis.fetch = originalFetch;
  });

  await withTimeout(new Promise((resolve) => {
    stream.addEventListener("open", resolve, { once: true });
  }));
  abortActiveApiRequests();
  assert.equal(stream.readyState, 2);
  await delay(320);
  assert.equal(streamRequests, 1);
});

test("logout closes SSE without reconnecting and login rotates it with the new token", async (t) => {
  abortActiveApiRequests();
  markBackendOnline();
  storage.clear();
  storage.set("token", "old-access-token");

  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    const headers = new Headers(init.headers);
    requests.push({
      url: String(input),
      authorization: headers.get("Authorization"),
      signal: init.signal,
    });
    if (!headers.has("Authorization")) {
      return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    return pendingSseResponse(init.signal);
  };

  const streamUrl = "/api/v1/courses/course-auth/knowledge/build/stream";
  let currentStream = openAuthenticatedSse(streamUrl);
  const rebuildStream = () => {
    currentStream = openAuthenticatedSse(streamUrl);
  };
  browserWindow.addEventListener(API_AUTH_CHANGED_EVENT, rebuildStream);
  t.after(() => {
    browserWindow.removeEventListener(API_AUTH_CHANGED_EVENT, rebuildStream);
    currentStream.close();
    abortActiveApiRequests();
    markBackendOnline();
    globalThis.fetch = originalFetch;
  });

  await withTimeout((async () => {
    while (requests.length < 1) await delay(5);
  })());
  const oldIdentityStream = currentStream;
  const initialGeneration = getApiAuthGeneration();

  storage.delete("token");
  abortActiveApiRequests();

  assert.equal(oldIdentityStream.readyState, 2, "logout must synchronously close the old identity stream");
  assert.equal(requests[0].signal.aborted, true);
  assert.equal(getApiAuthGeneration(), initialGeneration);
  await delay(20);
  assert.equal(requests.length, 1, "logout must not start an anonymous replacement stream");

  storage.set("token", "new-access-token");
  notifyApiAuthChanged();

  assert.equal(getApiAuthGeneration(), initialGeneration + 1);
  await withTimeout((async () => {
    while (requests.length < 2) await delay(5);
  })());
  assert.equal(requests[1].url, requests[0].url);
  assert.equal(requests[1].authorization, "Bearer new-access-token");
  await delay(20);
  assert.equal(requests.length, 2, "one auth generation must create only one replacement stream");
  assert.equal(requests.every((request) => !request.url.includes("access-token")), true);
});

test("auth notification does not abort ordinary tracked API requests", async (t) => {
  abortActiveApiRequests();
  markBackendOnline();
  storage.clear();
  storage.set("token", "new-access-token");

  const originalFetch = globalThis.fetch;
  let requestSignal;
  let resolveFetch;
  globalThis.fetch = async (_input, init = {}) => {
    requestSignal = init.signal;
    return new Promise((resolve) => {
      resolveFetch = resolve;
    });
  };
  t.after(() => {
    abortActiveApiRequests();
    markBackendOnline();
    globalThis.fetch = originalFetch;
  });

  const request = runTrackedApiFetch(
    "/api/v1/courses/course-auth/runtime",
    { method: "GET" },
    async (response) => response.text(),
  );
  await withTimeout((async () => {
    while (!requestSignal || !resolveFetch) await delay(5);
  })());

  notifyApiAuthChanged();
  assert.equal(requestSignal.aborted, false);

  resolveFetch(new Response("ok", { status: 200 }));
  assert.equal(await withTimeout(request), "ok");
});
