import { StringDecoder } from "node:string_decoder";

import type {
  LogBatch,
  LogLevel,
  LogRecord,
  LogSide,
  LogSnapshot,
  LogSource,
} from "../../shared-types.js";

export interface LogWriter {
  write(content: string): Promise<void> | void;
  close(): Promise<void> | void;
}

interface LogHubOptions {
  bufferLimit?: number;
  batchIntervalMs?: number;
  maxMessageBytes?: number;
  now?: () => Date;
}

interface AppendLogInput {
  side: LogSide;
  source: LogSource;
  level: LogLevel;
  scope: string;
  message: string;
}

const DEFAULT_BUFFER_LIMIT = 5_000;
const DEFAULT_BATCH_INTERVAL_MS = 100;
const DEFAULT_MAX_MESSAGE_BYTES = 32 * 1024;
const REDACTED = "[REDACTED]";

const replaceAllLiteral = (value: string, needle: string): string =>
  needle ? value.split(needle).join(REDACTED) : value;

const truncateUtf8 = (value: string, maxBytes: number): string => {
  const buffer = Buffer.from(value);
  if (buffer.length <= maxBytes) return value;
  let end = Math.max(0, maxBytes);
  const decoder = new TextDecoder("utf-8", { fatal: true });
  while (end > 0) {
    try {
      return `${decoder.decode(buffer.subarray(0, end))}…[已截断，原始 ${buffer.length} 字节]`;
    } catch {
      end -= 1;
    }
  }
  return `[已截断，原始 ${buffer.length} 字节]`;
};

/** 在日志进入内存、文件或 renderer 前执行统一脱敏与限长。 */
export const sanitizeLogMessage = (
  rawMessage: string,
  sensitiveValues: readonly string[],
  maxBytes = DEFAULT_MAX_MESSAGE_BYTES,
): string => {
  let message = rawMessage;
  for (const value of sensitiveValues) {
    if (value.length >= 4) message = replaceAllLiteral(message, value);
  }
  message = message
    .replace(/(authorization\s*:\s*bearer\s+)[^\s"',;]+/gi, `$1${REDACTED}`)
    .replace(
      /((?:api[_-]?key|token|secret|password)\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;]+)/gi,
      `$1${REDACTED}`,
    )
    .replace(/data:image\/[a-z0-9.+-]+;base64,[a-z0-9+/=_-]+/gi, `data:image/[REDACTED]`);
  return truncateUtf8(message, Math.max(1, maxBytes));
};

export const inferBackendLevel = (line: string): LogLevel => {
  const normalized = line.trimStart();
  const structuredLevel = normalized.match(
    /^(?:[^|\r\n]{1,80}\|\s*)?(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)(?=\s|:|\|)/i,
  )?.[1]?.toUpperCase();
  if (structuredLevel === "DEBUG") return "debug";
  if (structuredLevel === "WARN" || structuredLevel === "WARNING") return "warn";
  if (structuredLevel === "ERROR" || structuredLevel === "CRITICAL") {
    return "error";
  }
  if (/^Traceback\b/i.test(normalized)) return "error";
  return "info";
};

/** 将任意分块的 UTF-8 子进程输出还原为完整日志行。 */
export class BackendLineDecoder {
  private readonly decoder = new StringDecoder("utf8");
  private pending = "";

  constructor(private readonly onLine: (line: string) => void) {}

  write(chunk: Buffer | string): void {
    this.pending += typeof chunk === "string" ? chunk : this.decoder.write(chunk);
    this.drainLines();
  }

  end(chunk?: Buffer | string): void {
    if (chunk !== undefined) this.write(chunk);
    this.pending += this.decoder.end();
    this.drainLines();
    if (this.pending) {
      this.onLine(this.pending.replace(/\r$/, ""));
      this.pending = "";
    }
  }

  private drainLines(): void {
    let newline = this.pending.indexOf("\n");
    while (newline >= 0) {
      const line = this.pending.slice(0, newline).replace(/\r$/, "");
      this.pending = this.pending.slice(newline + 1);
      this.onLine(line);
      newline = this.pending.indexOf("\n");
    }
  }
}

/** Electron 主进程内的日志汇聚、缓存与批量分发中心。 */
export class LogHub {
  private readonly buffers: LogSnapshot = { frontend: [], backend: [] };
  private readonly subscribers = new Set<(batch: LogBatch) => void>();
  private readonly sensitiveValues = new Set<string>();
  private readonly bufferLimit: number;
  private readonly batchIntervalMs: number;
  private readonly maxMessageBytes: number;
  private readonly now: () => Date;
  private readonly writers: Partial<Record<LogSide, LogWriter>> = {};
  private pendingBatch: LogRecord[] = [];
  private batchTimer: ReturnType<typeof setTimeout> | null = null;
  private nextId = 1;
  private closed = false;

  constructor(options: LogHubOptions = {}) {
    this.bufferLimit = options.bufferLimit ?? DEFAULT_BUFFER_LIMIT;
    this.batchIntervalMs = options.batchIntervalMs ?? DEFAULT_BATCH_INTERVAL_MS;
    this.maxMessageBytes = options.maxMessageBytes ?? DEFAULT_MAX_MESSAGE_BYTES;
    this.now = options.now ?? (() => new Date());
  }

  setWriter(side: LogSide, writer: LogWriter): void {
    this.writers[side] = writer;
  }

  addSensitiveValue(value: string): void {
    if (value.length >= 4) this.sensitiveValues.add(value);
  }

  append(input: AppendLogInput): LogRecord | null {
    if (this.closed) return null;
    const record: LogRecord = {
      id: this.nextId,
      timestamp: this.now().toISOString(),
      side: input.side,
      source: input.source,
      level: input.level,
      scope: input.scope,
      message: sanitizeLogMessage(
        String(input.message),
        [...this.sensitiveValues],
        this.maxMessageBytes,
      ),
    };
    this.nextId += 1;

    const buffer = this.buffers[input.side];
    buffer.push(record);
    if (buffer.length > this.bufferLimit) {
      buffer.splice(0, buffer.length - this.bufferLimit);
    }
    this.pendingBatch.push(record);
    this.scheduleBatch();

    const writer = this.writers[input.side];
    if (writer) {
      const prefix = `${record.timestamp} ${record.level.toUpperCase().padEnd(5)} `
        + `[${record.source}/${record.scope}] `;
      const content = `${record.message
        .split(/\r?\n/)
        .map((line) => `${prefix}${line}`)
        .join("\n")}\n`;
      void Promise.resolve(writer.write(content)).catch(() => undefined);
    }
    return record;
  }

  getSnapshot(): LogSnapshot {
    return {
      frontend: [...this.buffers.frontend],
      backend: [...this.buffers.backend],
    };
  }

  getRecent(side: LogSide, limit: number): LogRecord[] {
    return this.buffers[side].slice(-Math.max(0, limit));
  }

  clear(side: LogSide): void {
    this.buffers[side] = [];
    this.pendingBatch = this.pendingBatch.filter((record) => record.side !== side);
  }

  subscribe(listener: (batch: LogBatch) => void): () => void {
    this.subscribers.add(listener);
    return () => this.subscribers.delete(listener);
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    if (this.batchTimer) {
      clearTimeout(this.batchTimer);
      this.batchTimer = null;
    }
    this.publishBatch();
    await Promise.all(
      Object.values(this.writers).map((writer) => Promise.resolve(writer?.close())),
    );
  }

  private scheduleBatch(): void {
    if (this.batchTimer) return;
    this.batchTimer = setTimeout(() => {
      this.batchTimer = null;
      this.publishBatch();
    }, this.batchIntervalMs);
  }

  private publishBatch(): void {
    if (this.pendingBatch.length === 0) return;
    const batch = { records: this.pendingBatch };
    this.pendingBatch = [];
    for (const subscriber of this.subscribers) {
      try {
        subscriber(batch);
      } catch {
        // 日志观察者不能反向破坏日志生产者。
      }
    }
  }
}
