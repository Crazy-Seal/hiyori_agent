import assert from "node:assert/strict";
import { test } from "node:test";

import {
  UnexpectedSseEofError,
  consumeSseStream,
  type SseStreamHandlers,
} from "../electron/sse-stream.js";

const encoder = new TextEncoder();

const streamFrom = (...chunks: string[]): ReadableStream<Uint8Array> =>
  new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });

const collect = () => {
  const chunks: string[] = [];
  const tools: string[] = [];
  const interrupts: unknown[] = [];
  const handlers: SseStreamHandlers = {
    onChunk: (chunk) => chunks.push(chunk),
    onToolCall: (toolName) => tools.push(toolName),
    onInterrupt: (interrupt) => interrupts.push(interrupt),
  };
  return { chunks, tools, interrupts, handlers };
};

test("多个文本 chunk 后提前 EOF 必须失败", async () => {
  const observed = collect();
  const stream = streamFrom(
    'data: {"response":"前半"}\n\n',
    'data: {"response":"后半"}\n\n',
  );

  await assert.rejects(
    consumeSseStream(stream, observed.handlers, "流式响应失败"),
    UnexpectedSseEofError,
  );
  assert.deepEqual(observed.chunks, ["前半", "后半"]);
});

test("零 chunk 提前 EOF 必须失败", async () => {
  await assert.rejects(
    consumeSseStream(streamFrom(), collect().handlers, "流式响应失败"),
    UnexpectedSseEofError,
  );
});

test("残留块中的 DONE 可以正常完成", async () => {
  const observed = collect();
  const result = await consumeSseStream(
    streamFrom('data: {"response":"完成"}\n\ndata: [DONE]'),
    observed.handlers,
    "流式响应失败",
  );

  assert.deepEqual(result, { response: "完成", model: "" });
});

test("残留块中的 interrupt 返回中断终态", async () => {
  const observed = collect();
  const result = await consumeSseStream(
    streamFrom(
      'event: interrupt\ndata: {"value":{"type":"screenshot_request","request_id":"r1","message":"允许？"}}',
    ),
    observed.handlers,
    "流式响应失败",
  );

  assert.equal(result.interrupted, true);
  assert.equal(observed.interrupts.length, 1);
});

test("残留块中的 error 立即失败", async () => {
  await assert.rejects(
    consumeSseStream(
      streamFrom('event: error\ndata: {"detail":"模型失败"}'),
      collect().handlers,
      "流式响应失败",
    ),
    /模型失败/,
  );
});

test("明确终态后的事件被忽略", async () => {
  const observed = collect();
  const result = await consumeSseStream(
    streamFrom(
      'data: {"response":"完成"}\n\ndata: [DONE]\n\ndata: {"response":"不应出现"}\n\n',
    ),
    observed.handlers,
    "流式响应失败",
  );

  assert.equal(result.response, "完成");
  assert.deepEqual(observed.chunks, ["完成"]);
});
