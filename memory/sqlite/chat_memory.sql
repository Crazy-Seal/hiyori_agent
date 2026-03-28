CREATE TABLE IF NOT EXISTS chat_history (
                                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                                            thread_id TEXT NOT NULL,           -- 对应 session_id
                                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                            role TEXT NOT NULL,                 -- 'Human' 或 'AI' 或 'Tool
                                            content TEXT NOT NULL
);

CREATE INDEX idx_thread_time ON chat_history (thread_id, timestamp);

-- 短期记忆摘要
CREATE TABLE IF NOT EXISTS short_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    content TEXT NOT NULL
);

CREATE INDEX idx_short_thread_time ON short_memory (thread_id, timestamp);
