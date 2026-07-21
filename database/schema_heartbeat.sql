-- ============================================================
-- schema_heartbeat.sql — 心跳监控数据库表结构
-- 数据库: SQLite (ako_hub.db)
-- 文档编号: AGE-TECH-AKO-HUB-020 §Schema
-- ============================================================

-- ── Agent 注册表 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents_registry (
    agent_id          TEXT PRIMARY KEY,
    display_name      TEXT    NOT NULL DEFAULT '',
    agent_type        TEXT    NOT NULL DEFAULT 'unknown',
    alert_level       TEXT    NOT NULL DEFAULT 'warning',
    heartbeat_interval INTEGER NOT NULL DEFAULT 30,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 心跳记录表 ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS heartbeats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          TEXT    NOT NULL,
    timestamp         TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'alive',
    cpu_percent       REAL,
    memory_mb         REAL,
    disk_percent      REAL,
    task_total        INTEGER DEFAULT 0,
    task_success      INTEGER DEFAULT 0,
    task_failed       INTEGER DEFAULT 0,
    last_task         TEXT,
    last_task_status  TEXT,
    response_time_ms  REAL,
    FOREIGN KEY (agent_id) REFERENCES agents_registry(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_time
    ON heartbeats(agent_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp
    ON heartbeats(timestamp);

-- ── 日志表 ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT,
    agent_id    TEXT    NOT NULL,
    level       TEXT    NOT NULL DEFAULT 'INFO',
    message     TEXT    NOT NULL DEFAULT '',
    context     TEXT,           -- JSON 扩展字段
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agents_registry(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_logs_agent_time
    ON logs(agent_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_logs_level
    ON logs(level);

CREATE INDEX IF NOT EXISTS idx_logs_trace_id
    ON logs(trace_id);

-- ── 告警表 ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT    NOT NULL,
    alert_type      TEXT    NOT NULL,
    severity        TEXT    NOT NULL DEFAULT 'info',
    message         TEXT    NOT NULL DEFAULT '',
    acknowledged    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents_registry(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_agent
    ON alerts(agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_unresolved
    ON alerts(resolved_at) WHERE resolved_at IS NULL;

-- ── 心跳数据清理（保留最近 7 天） ─────────────────────────────
CREATE TRIGGER IF NOT EXISTS cleanup_old_heartbeats
AFTER INSERT ON heartbeats
BEGIN
    DELETE FROM heartbeats
    WHERE timestamp < datetime('now', '-7 days');
END;

-- ── 日志清理（保留最近 30 天） ────────────────────────────────
CREATE TRIGGER IF NOT EXISTS cleanup_old_logs
AFTER INSERT ON logs
BEGIN
    DELETE FROM logs
    WHERE timestamp < datetime('now', '-30 days');
END;
