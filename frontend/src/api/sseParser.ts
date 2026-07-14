export interface ParsedSseMessage {
  type: string;
  data: string;
}

export interface ParsedSseEventBlock {
  message: ParsedSseMessage | null;
  lastEventId: string | null;
  retryMs: number | null;
}

export function parseSseEventBlock(block: string): ParsedSseEventBlock {
  let eventType = "message";
  let lastEventId: string | null = null;
  let retryMs: number | null = null;
  let sawData = false;
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;

    const separatorIndex = line.indexOf(":");
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
    let value = separatorIndex === -1 ? "" : line.slice(separatorIndex + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") {
      eventType = value || "message";
    } else if (field === "data") {
      sawData = true;
      dataLines.push(value);
    } else if (field === "id" && !value.includes("\0")) {
      lastEventId = value;
    } else if (field === "retry" && /^\d+$/.test(value)) {
      retryMs = Number(value);
    }
  }

  return {
    message: sawData ? { type: eventType, data: dataLines.join("\n") } : null,
    lastEventId,
    retryMs,
  };
}
