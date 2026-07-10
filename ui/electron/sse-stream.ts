import type {
  ChatInterruptPayload,
  ChatResult,
} from "../shared-types.js";

export class UnexpectedSseEofError extends Error {
  constructor(message = "SSE 流在收到明确终态前结束") {
    super(message);
    this.name = "UnexpectedSseEofError";
  }
}

export type SseStreamHandlers = {
  onChunk?: (chunk: string, aggregated: string) => void;
  onToolCall?: (toolName: string) => void;
  onInterrupt?: (interrupt: ChatInterruptPayload) => void;
};

type StreamTerminal =
  | { type: "done" }
  | { type: "interrupt"; data: ChatInterruptPayload };

type ParsedPayload = {
  response?: string;
  detail?: string;
  tool_name?: string;
};

/** 消费后端 SSE；只有 DONE、interrupt 或 error 才允许结束请求。 */
export const consumeSseStream = async (
  stream: ReadableStream<Uint8Array>,
  handlers: SseStreamHandlers,
  errorFallback: string,
): Promise<ChatResult> => {
  const decoder = new TextDecoder("utf-8");
  const reader = stream.getReader();
  let buffer = "";
  let aggregatedResponse = "";
  let terminal: StreamTerminal | undefined;

  const processEventBlock = (block: string): StreamTerminal | undefined => {
    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (dataLines.length === 0) {
      return undefined;
    }

    const dataText = dataLines.join("\n");
    if (dataText === "[DONE]") {
      return { type: "done" };
    }

    const parsed = JSON.parse(dataText) as ParsedPayload;
    if (eventName === "interrupt") {
      const interrupt = parsed as unknown as ChatInterruptPayload;
      handlers.onInterrupt?.(interrupt);
      return { type: "interrupt", data: interrupt };
    }
    if (eventName === "error") {
      throw new Error(parsed.detail || errorFallback);
    }
    if (eventName === "tool_call") {
      if (typeof parsed.tool_name === "string" && parsed.tool_name.length > 0) {
        handlers.onToolCall?.(parsed.tool_name);
      }
      return undefined;
    }
    if (typeof parsed.response === "string" && parsed.response.length > 0) {
      aggregatedResponse += parsed.response;
      handlers.onChunk?.(parsed.response, aggregatedResponse);
    }
    return undefined;
  };

  while (!terminal) {
    const readResult = await reader.read();
    if (readResult.done) {
      buffer += decoder.decode();
      break;
    }

    buffer += decoder.decode(readResult.value, { stream: true });
    const normalized = buffer.replaceAll("\r\n", "\n");
    const eventBlocks = normalized.split("\n\n");
    buffer = eventBlocks.pop() ?? "";

    for (const block of eventBlocks) {
      terminal = processEventBlock(block);
      if (terminal) {
        break;
      }
    }
  }

  if (!terminal) {
    const remaining = buffer.trim();
    if (remaining.length > 0) {
      terminal = processEventBlock(remaining);
    }
  }

  if (!terminal) {
    throw new UnexpectedSseEofError();
  }
  if (terminal.type === "interrupt") {
    return {
      interrupted: true,
      interruptData: terminal.data,
      response: aggregatedResponse,
      model: "",
    };
  }
  return { response: aggregatedResponse, model: "" };
};
