import { appendFile, mkdir, rename, rm, stat } from "node:fs/promises";
import path from "node:path";

export interface RollingLogWriterOptions {
  directory: string;
  fileName: string;
  maxBytes: number;
  maxFiles: number;
  onError?: (error: unknown) => void;
}

const isMissingFile = (error: unknown): boolean =>
  error instanceof Error && "code" in error && error.code === "ENOENT";

/**
 * 串行追加并按大小轮换的轻量日志写入器。
 *
 * 写入错误会报告给回调，但不会向调用方传播，避免日志故障影响应用主流程。
 */
export class RollingLogWriter {
  private readonly filePath: string;
  private readonly onError: (error: unknown) => void;
  private queue: Promise<void> = Promise.resolve();
  private currentBytes: number | null = null;
  private closed = false;

  constructor(private readonly options: RollingLogWriterOptions) {
    this.filePath = path.join(options.directory, options.fileName);
    this.onError = options.onError ?? (() => undefined);
  }

  write(content: string): Promise<void> {
    if (this.closed) return Promise.resolve();
    const task = this.queue
      .then(() => this.writeInternal(content))
      .catch((error) => {
        this.onError(error);
      });
    this.queue = task;
    return task;
  }

  flush(): Promise<void> {
    return this.queue;
  }

  async close(): Promise<void> {
    await this.queue;
    this.closed = true;
  }

  private async writeInternal(content: string): Promise<void> {
    await mkdir(this.options.directory, { recursive: true });
    if (this.currentBytes === null) {
      try {
        this.currentBytes = (await stat(this.filePath)).size;
      } catch (error) {
        if (!isMissingFile(error)) throw error;
        this.currentBytes = 0;
      }
    }

    const bytes = Buffer.byteLength(content);
    if (this.currentBytes > 0 && this.currentBytes + bytes > this.options.maxBytes) {
      await this.rotate();
      this.currentBytes = 0;
    }
    await appendFile(this.filePath, content, "utf8");
    this.currentBytes += bytes;
  }

  private async rotate(): Promise<void> {
    const maxFiles = Math.max(1, this.options.maxFiles);
    if (maxFiles === 1) {
      await rm(this.filePath, { force: true });
      return;
    }

    for (let index = maxFiles - 1; index >= 1; index -= 1) {
      const source = index === 1 ? this.filePath : `${this.filePath}.${index - 1}`;
      const target = `${this.filePath}.${index}`;
      await rm(target, { force: true });
      try {
        await rename(source, target);
      } catch (error) {
        if (!isMissingFile(error)) throw error;
      }
    }
  }
}
