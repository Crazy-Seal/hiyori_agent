import type {
  LogLevel,
  LogRecord,
  LogSide,
  LogSnapshot,
  LogSource,
} from "../../shared-types.js";

export interface LogFilter {
  query: string;
  minimumLevel: LogLevel;
  sources: ReadonlySet<LogSource>;
}

const LOG_LEVEL_RANK: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

export class LogViewerModel {
  private readonly records: LogSnapshot;
  private readonly pending: LogRecord[] = [];
  private paused = false;

  constructor(snapshot: LogSnapshot, private readonly limit = 5_000) {
    this.records = {
      frontend: snapshot.frontend.slice(-limit),
      backend: snapshot.backend.slice(-limit),
    };
  }

  append(incoming: readonly LogRecord[]): void {
    if (this.paused) {
      this.pending.push(...incoming);
      return;
    }
    this.apply(incoming);
  }

  setPaused(paused: boolean): void {
    if (this.paused === paused) return;
    this.paused = paused;
    if (!paused && this.pending.length > 0) {
      const pending = this.pending.splice(0);
      this.apply(pending);
    }
  }

  isPaused(): boolean {
    return this.paused;
  }

  getRecords(side: LogSide): readonly LogRecord[] {
    return this.records[side];
  }

  clear(side: LogSide): void {
    this.records[side] = [];
    for (let index = this.pending.length - 1; index >= 0; index -= 1) {
      if (this.pending[index]?.side === side) this.pending.splice(index, 1);
    }
  }

  filter(side: LogSide, filter: LogFilter): LogRecord[] {
    const query = filter.query.trim().toLocaleLowerCase();
    return this.records[side].filter((record) => (
      LOG_LEVEL_RANK[record.level] >= LOG_LEVEL_RANK[filter.minimumLevel]
      && (filter.sources.size === 0 || filter.sources.has(record.source))
      && (!query || `${record.scope} ${record.message}`.toLocaleLowerCase().includes(query))
    ));
  }

  private apply(incoming: readonly LogRecord[]): void {
    const knownIds = new Set([
      ...this.records.frontend.map((record) => record.id),
      ...this.records.backend.map((record) => record.id),
    ]);
    for (const record of incoming) {
      if (knownIds.has(record.id)) continue;
      knownIds.add(record.id);
      const sideRecords = this.records[record.side];
      sideRecords.push(record);
      if (sideRecords.length > this.limit) {
        sideRecords.splice(0, sideRecords.length - this.limit);
      }
    }
  }
}
