import assert from "node:assert/strict";
import { test } from "node:test";

import { pasteScreenActionText } from "../electron/screen-action-input.js";

const keys = {
  leftControl: "LeftControl",
  v: "V",
  enter: "Enter",
};

const createClipboard = (initialText = "old text") => {
  const writes: string[] = [];
  let text = initialText;

  return {
    writes,
    api: {
      readText: () => text,
      writeText: (nextText: string) => {
        writes.push(nextText);
        text = nextText;
      },
    },
  };
};

const createRichClipboard = () => {
  const image = { id: "old image" };
  const writes: unknown[] = [];
  const events: Array<[string, string]> = [];
  let text = "old text";

  return {
    image,
    writes,
    events,
    api: {
      readText: () => text,
      writeText: (nextText: string) => {
        events.push(["writeText", nextText]);
        text = nextText;
      },
      availableFormats: () => ["text/plain", "text/html", "text/rtf", "image/png"],
      readHTML: () => "<b>old html</b>",
      readRTF: () => "{\\rtf1 old}",
      readImage: () => image,
      write: (data: unknown) => {
        events.push(["write", JSON.stringify(data)]);
        writes.push(data);
      },
    },
  };
};

const createFileClipboard = () => {
  const events: Array<[string, string]> = [];

  return {
    events,
    api: {
      readText: () => "",
      writeText: (nextText: string) => {
        events.push(["writeText", nextText]);
      },
      availableFormats: () => ["FileNameW"],
      readHTML: () => "",
      readRTF: () => "",
      readImage: () => ({ id: "unused image" }),
      write: (data: unknown) => {
        events.push(["write", JSON.stringify(data)]);
      },
    },
  };
};

const createKeyboard = (failOnPress?: unknown) => {
  const events: Array<[string, unknown]> = [];

  return {
    events,
    api: {
      type: async (_text: string) => {
        events.push(["type", _text]);
      },
      pressKey: async (key: unknown) => {
        events.push(["press", key]);
        if (key === failOnPress) {
          throw new Error("press failed");
        }
      },
      releaseKey: async (key: unknown) => {
        events.push(["release", key]);
      },
    },
  };
};

test("文本输入写入剪贴板并通过 Ctrl+V 粘贴，不调用 keyboard.type", async () => {
  const clipboard = createClipboard();
  const keyboard = createKeyboard();

  await pasteScreenActionText({
    text: "庆祝你满血复活",
    pressEnter: false,
    clipboard: clipboard.api,
    keyboard: keyboard.api,
    keys,
  });

  assert.deepEqual(clipboard.writes, ["庆祝你满血复活", "old text"]);
  assert.deepEqual(keyboard.events, [
    ["press", "LeftControl"],
    ["press", "V"],
    ["release", "V"],
    ["release", "LeftControl"],
  ]);
});

test("press_enter=true 时粘贴后按 Enter", async () => {
  const clipboard = createClipboard();
  const keyboard = createKeyboard();

  await pasteScreenActionText({
    text: "hello",
    pressEnter: true,
    clipboard: clipboard.api,
    keyboard: keyboard.api,
    keys,
  });

  assert.deepEqual(keyboard.events.slice(-2), [
    ["press", "Enter"],
    ["release", "Enter"],
  ]);
});

test("粘贴失败时仍释放已按下的 Ctrl 并恢复剪贴板文本", async () => {
  const clipboard = createClipboard("before");
  const keyboard = createKeyboard("V");

  await assert.rejects(
    pasteScreenActionText({
      text: "庆祝你满血复活",
      pressEnter: true,
      clipboard: clipboard.api,
      keyboard: keyboard.api,
      keys,
    }),
    /press failed/,
  );

  assert.deepEqual(clipboard.writes, ["庆祝你满血复活", "before"]);
  assert.deepEqual(keyboard.events, [
    ["press", "LeftControl"],
    ["press", "V"],
    ["release", "LeftControl"],
  ]);
});

test("恢复剪贴板时使用 clipboard.write(data) 一次性保留 HTML、RTF 和图片格式", async () => {
  const clipboard = createRichClipboard();
  const keyboard = createKeyboard();

  await pasteScreenActionText({
    text: "hello",
    pressEnter: false,
    clipboard: clipboard.api,
    keyboard: keyboard.api,
    keys,
  });

  assert.equal(clipboard.writes.length, 1);
  assert.deepEqual(clipboard.writes[0], {
    text: "old text",
    html: "<b>old html</b>",
    rtf: "{\\rtf1 old}",
    image: clipboard.image,
  });
  assert.deepEqual(clipboard.events, [
    ["writeText", "hello"],
    ["write", JSON.stringify({
      text: "old text",
      html: "<b>old html</b>",
      rtf: "{\\rtf1 old}",
      image: clipboard.image,
    })],
  ]);
});

test("检测到 Windows 文件剪贴板格式时拒绝粘贴以避免覆盖无法可靠恢复的数据", async () => {
  const clipboard = createFileClipboard();
  const keyboard = createKeyboard();

  await assert.rejects(
    pasteScreenActionText({
      text: "hello",
      pressEnter: false,
      clipboard: clipboard.api,
      keyboard: keyboard.api,
      keys,
    }),
    /unsupported clipboard format: FileNameW/,
  );

  assert.deepEqual(clipboard.events, []);
  assert.deepEqual(keyboard.events, []);
});
