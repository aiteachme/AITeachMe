import assert from "node:assert/strict";
import test from "node:test";

import { parseSseEventBlock } from "../src/api/sseParser.ts";

test("parses named CRLF events with multiline data", () => {
  assert.deepEqual(
    parseSseEventBlock(
      "event: snapshot\r\nid: build-42\r\ndata: first line\r\ndata: second line\r\nretry: 1500\r\n",
    ),
    {
      message: { type: "snapshot", data: "first line\nsecond line" },
      lastEventId: "build-42",
      retryMs: 1500,
    },
  );
});

test("ignores comments and keeps retry metadata without dispatching data", () => {
  assert.deepEqual(parseSseEventBlock(": keepalive\nretry: 900\n"), {
    message: null,
    lastEventId: null,
    retryMs: 900,
  });
});

test("keeps id metadata from blocks without data", () => {
  assert.deepEqual(parseSseEventBlock("id: event-7\n"), {
    message: null,
    lastEventId: "event-7",
    retryMs: null,
  });
});
