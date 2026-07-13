export type TextClipboard = {
  readText: () => string;
  writeText: (text: string) => void;
  availableFormats?: () => string[];
  readHTML?: () => string;
  readRTF?: () => string;
  readImage?: () => unknown;
  write?: (data: ClipboardWriteData) => void;
};

export type PasteKeyboard<KeyType> = {
  pressKey: (...keys: KeyType[]) => Promise<unknown>;
  releaseKey: (...keys: KeyType[]) => Promise<unknown>;
};

export type PasteKeys<KeyType> = {
  leftControl: KeyType;
  v: KeyType;
  enter: KeyType;
};

export type PasteScreenActionTextOptions<KeyType> = {
  text: string;
  pressEnter: boolean;
  clipboard: TextClipboard;
  keyboard: PasteKeyboard<KeyType>;
  keys: PasteKeys<KeyType>;
};

type ClipboardWriteData = {
  text?: string;
  html?: string;
  rtf?: string;
  image?: unknown;
};

type ClipboardSnapshot =
  | {
      kind: "data";
      data: ClipboardWriteData;
    }
  | {
      kind: "text";
      text: string;
    };

const canSnapshotData = (
  clipboard: TextClipboard,
): clipboard is TextClipboard & Required<Pick<TextClipboard, "availableFormats" | "write">> =>
  typeof clipboard.availableFormats === "function" &&
  typeof clipboard.write === "function";

const normalizeFormat = (format: string): string => format.toLowerCase();

const isFileClipboardFormat = (format: string): boolean => {
  const normalized = normalizeFormat(format);
  return normalized.includes("filename") || normalized.includes("hdrop");
};

const isSupportedClipboardFormat = (format: string): boolean => {
  const normalized = normalizeFormat(format);
  return (
    normalized === "text/plain" ||
    normalized === "text/html" ||
    normalized === "text/rtf" ||
    normalized.startsWith("image/")
  );
};

const hasFormat = (formats: string[], predicate: (format: string) => boolean): boolean =>
  formats.some((format) => predicate(normalizeFormat(format)));

const createClipboardSnapshot = (clipboard: TextClipboard): ClipboardSnapshot => {
  if (!canSnapshotData(clipboard)) {
    return {
      kind: "text",
      text: clipboard.readText(),
    };
  }

  const formats = clipboard.availableFormats();
  const unsupportedFormat = formats.find((format) => !isSupportedClipboardFormat(format));
  if (unsupportedFormat) {
    const message = isFileClipboardFormat(unsupportedFormat)
      ? "当前用户剪贴板中包含文件，无法在粘贴后可靠恢复。为避免覆盖剪贴板，已取消这次文本输入。"
      : `当前用户剪贴板中包含当前无法可靠恢复的格式（${unsupportedFormat}），无法在粘贴后可靠恢复。为避免覆盖剪贴板，已取消这次文本输入。`;
    throw new Error(message);
  }

  const data: ClipboardWriteData = {};
  if (hasFormat(formats, (format) => format === "text/plain")) {
    data.text = clipboard.readText();
  }
  if (hasFormat(formats, (format) => format === "text/html") && typeof clipboard.readHTML === "function") {
    data.html = clipboard.readHTML();
  }
  if (hasFormat(formats, (format) => format === "text/rtf") && typeof clipboard.readRTF === "function") {
    data.rtf = clipboard.readRTF();
  }
  if (hasFormat(formats, (format) => format.startsWith("image/")) && typeof clipboard.readImage === "function") {
    data.image = clipboard.readImage();
  }

  return {
    kind: "data",
    data,
  };
};

const restoreClipboardSnapshot = (
  clipboard: TextClipboard,
  snapshot: ClipboardSnapshot,
): void => {
  if (snapshot.kind === "text" || !canSnapshotData(clipboard)) {
    if (snapshot.kind !== "text") {
      return;
    }
    clipboard.writeText(snapshot.text);
    return;
  }

  clipboard.write(snapshot.data);
};

const releaseIfPressed = async <KeyType>(
  keyboard: PasteKeyboard<KeyType>,
  key: KeyType,
  pressed: boolean,
): Promise<unknown> => {
  if (pressed) {
    await keyboard.releaseKey(key);
  }
  return undefined;
};

const throwFirstError = (errors: unknown[]): void => {
  if (errors.length > 0) {
    throw errors[0];
  }
};

export const pasteScreenActionText = async <KeyType>({
  text,
  pressEnter,
  clipboard,
  keyboard,
  keys,
}: PasteScreenActionTextOptions<KeyType>): Promise<void> => {
  if (!text) {
    return;
  }

  const clipboardSnapshot = createClipboardSnapshot(clipboard);
  let controlPressed = false;
  let vPressed = false;

  try {
    clipboard.writeText(text);
    await keyboard.pressKey(keys.leftControl);
    controlPressed = true;
    await keyboard.pressKey(keys.v);
    vPressed = true;
  } finally {
    const releaseErrors = await Promise.allSettled([
      releaseIfPressed(keyboard, keys.v, vPressed),
      releaseIfPressed(keyboard, keys.leftControl, controlPressed),
    ]);
    restoreClipboardSnapshot(clipboard, clipboardSnapshot);
    throwFirstError(
      releaseErrors
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => result.reason),
    );
  }

  if (pressEnter) {
    await keyboard.pressKey(keys.enter);
    await keyboard.releaseKey(keys.enter);
  }
};
