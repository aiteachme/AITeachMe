import assert from "node:assert/strict";
import test from "node:test";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { refreshQuestionTypeCatalogAfterUpdate } from "../src/components/exams/questionTypeCatalogCache.ts";

function deferred() {
  let resolve;
  const promise = new Promise((finish) => { resolve = finish; });
  return { promise, resolve };
}

function createClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

const installed = {
  id: 7, course_id: "course_a", type_key: "custom_example", status: "active",
  is_active: true, current_version_id: 10, current_version: "1.0.0",
};

for (const [operation, changes] of [
  ["deactivation", { status: "inactive", is_active: false }],
  ["version switch", { current_version_id: 11, current_version: "2.0.0" }],
]) {
  test(`a delayed catalog read cannot undo a confirmed ${operation}`, async (t) => {
    const client = createClient();
    t.after(() => client.clear());
    const queryKey = ["question-type-catalog", installed.course_id];
    client.setQueryData(queryKey, [installed]);
    const earlierRead = deferred();
    let earlierSignal;
    const pendingRead = client.fetchQuery({
      queryKey,
      queryFn: ({ signal }) => {
        earlierSignal = signal;
        // Deliberately ignore abort: even a late transport result must not win.
        return earlierRead.promise;
      },
    }).catch(() => undefined);
    const updated = { ...installed, ...changes };

    await refreshQuestionTypeCatalogAfterUpdate(client, installed.course_id, updated);
    earlierRead.resolve([installed]);
    await pendingRead;

    assert.deepEqual(client.getQueryData(queryKey), [updated]);
    assert.equal(earlierSignal.aborted, true);
    assert.equal(client.getQueryState(queryKey).isInvalidated, true);
  });
}

test("confirmation refreshes only the original course and retains the full server catalog", async (t) => {
  const client = createClient();
  t.after(() => client.clear());
  const originalKey = ["question-type-catalog", installed.course_id];
  const otherKey = ["question-type-catalog", "course_b"];
  const updated = { ...installed, status: "inactive", is_active: false };
  const newlyInstalled = { ...installed, id: 8 };
  const otherCourseType = { ...installed, id: 20, course_id: "course_b" };
  client.setQueryData(originalKey, [installed]);
  client.setQueryData(otherKey, [otherCourseType]);
  let originalReads = 0;
  let otherReads = 0;
  const originalObserver = new QueryObserver(client, {
    queryKey: originalKey,
    staleTime: Infinity,
    queryFn: async () => { originalReads += 1; return [updated, newlyInstalled]; },
  });
  const otherObserver = new QueryObserver(client, {
    queryKey: otherKey,
    staleTime: Infinity,
    queryFn: async () => { otherReads += 1; return [otherCourseType]; },
  });
  const unsubscribeOriginal = originalObserver.subscribe(() => {});
  const unsubscribeOther = otherObserver.subscribe(() => {});
  t.after(() => { unsubscribeOriginal(); unsubscribeOther(); });

  // The mutation still belongs to course_a even if course_b is now displayed.
  await refreshQuestionTypeCatalogAfterUpdate(client, installed.course_id, updated);

  assert.equal(originalReads, 1);
  assert.equal(otherReads, 0);
  assert.deepEqual(client.getQueryData(originalKey), [updated, newlyInstalled]);
  assert.deepEqual(client.getQueryData(otherKey), [otherCourseType]);
});
