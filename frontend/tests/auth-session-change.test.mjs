import assert from "node:assert/strict";
import test from "node:test";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

class BrowserWindowStub extends EventTarget {
  location = { search: "", protocol: "http:", hostname: "localhost" };
}

globalThis.window = new BrowserWindowStub();
const storage = new Map();
globalThis.localStorage = window.localStorage = {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
};

const { applyAuthSessionChange, AUTH_SESSION_QUERY_KEY } = await import("../src/lib/authSession.ts");
const { API_AUTH_CHANGED_EVENT, getApiAuthGeneration } = await import("../src/api/client.ts");

function session(userId, csrfToken = "csrf") {
  return {
    auth_enabled: true,
    auth_ready: true,
    csrf_token: csrfToken,
    current_user: { user_id: userId, is_authenticated: !userId.startsWith("guest") },
  };
}

function createClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flushNotifications() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("logout clears private cached data immediately and preserves browser UI preferences", () => {
  const client = createClient();
  client.setQueryData(AUTH_SESSION_QUERY_KEY, session("account-a"));
  client.setQueryData(["courses"], [{ course_id: "private-a" }]);
  client.setQueryData(["files-library"], { items: [{ id: "private-file-a" }] });
  client.setQueryData(["user-profile-page"], { notes: ["private-note-a"] });
  localStorage.setItem("theme", "dark");
  const generation = getApiAuthGeneration();
  let identityEvents = 0;
  const onIdentityChange = () => { identityEvents += 1; };
  window.addEventListener(API_AUTH_CHANGED_EVENT, onIdentityChange);
  try {
    const guest = session("guest-b");
    applyAuthSessionChange(client, guest);

    assert.equal(client.getQueryData(["courses"]), undefined);
    assert.equal(client.getQueryData(["files-library"]), undefined);
    assert.equal(client.getQueryData(["user-profile-page"]), undefined);
    assert.deepEqual(client.getQueryData(AUTH_SESSION_QUERY_KEY), guest);
    assert.equal(getApiAuthGeneration(), generation + 1);
    assert.equal(identityEvents, 1);
    assert.equal(localStorage.getItem("theme"), "dark");
  } finally {
    window.removeEventListener(API_AUTH_CHANGED_EVENT, onIdentityChange);
    client.clear();
  }
});

test("login cancels an old request and an observed query loads only the new user's response", async () => {
  const client = createClient();
  client.setQueryData(AUTH_SESSION_QUERY_KEY, session("guest-a"));
  const oldResponse = deferred();
  const newResponse = deferred();
  let requestIdentity = "guest-a";
  const observer = new QueryObserver(client, {
    queryKey: ["files-library"],
    queryFn: () => requestIdentity === "guest-a" ? oldResponse.promise : newResponse.promise,
  });
  const unsubscribe = observer.subscribe(() => {});
  try {
    requestIdentity = "account-b";
    applyAuthSessionChange(client, session("account-b"));
    assert.equal(client.getQueryData(["files-library"]), undefined);
    assert.equal(client.getQueryState(["files-library"]).fetchStatus, "fetching");

    // This transport ignores AbortSignal and still resolves after cancellation.
    oldResponse.resolve({ items: [{ id: "private-a" }] });
    await flushNotifications();
    assert.equal(client.getQueryData(["files-library"]), undefined);

    newResponse.resolve({ items: [{ id: "private-b" }] });
    await flushNotifications();
    assert.deepEqual(observer.getCurrentResult().data, { items: [{ id: "private-b" }] });
  } finally {
    unsubscribe();
    client.clear();
  }
});

test("a failed new-user refresh never restores the previous user's cached result", async () => {
  const client = createClient();
  client.setQueryData(AUTH_SESSION_QUERY_KEY, session("account-a"));
  client.setQueryData(["courses"], [{ course_id: "private-a" }]);
  const response = deferred();
  const observer = new QueryObserver(client, {
    queryKey: ["courses"],
    queryFn: () => response.promise,
    staleTime: Infinity,
  });
  const unsubscribe = observer.subscribe(() => {});
  try {
    applyAuthSessionChange(client, session("guest-b"));
    assert.equal(client.getQueryData(["courses"]), undefined);
    response.reject(new Error("new identity has no access"));
    await flushNotifications();
    assert.equal(observer.getCurrentResult().status, "error");
    assert.equal(observer.getCurrentResult().data, undefined);
  } finally {
    unsubscribe();
    client.clear();
  }
});

test("an earlier auth-session request cannot overwrite the new identity", async () => {
  const client = createClient();
  client.setQueryData(AUTH_SESSION_QUERY_KEY, session("account-a"));
  const oldResponse = deferred();
  const oldRequest = client.fetchQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: () => oldResponse.promise,
  }).catch(() => undefined);
  try {
    const nextSession = session("account-b");
    applyAuthSessionChange(client, nextSession);
    oldResponse.resolve(session("account-a"));
    await oldRequest;
    await flushNotifications();
    assert.deepEqual(client.getQueryData(AUTH_SESSION_QUERY_KEY), nextSession);
  } finally {
    client.clear();
  }
});

test("refreshing the same identity preserves cached content and identity generation", () => {
  const client = createClient();
  client.setQueryData(AUTH_SESSION_QUERY_KEY, session("account-a", "old-csrf"));
  client.setQueryData(["courses"], [{ course_id: "private-a" }]);
  const generation = getApiAuthGeneration();
  try {
    const refreshed = session("account-a", "new-csrf");
    applyAuthSessionChange(client, refreshed);
    assert.deepEqual(client.getQueryData(["courses"]), [{ course_id: "private-a" }]);
    assert.deepEqual(client.getQueryData(AUTH_SESSION_QUERY_KEY), refreshed);
    assert.equal(getApiAuthGeneration(), generation);
  } finally {
    client.clear();
  }
});
