-- ============================================================================
-- schema_router.sql — 意图路由系统数据库表
-- 文档编号: AGE-TECH-AKO-HUB-024
-- ============================================================================
-- 说明: agent_capabilities 表由 IntentRouter._init_db() 自动创建，
--       此文件用于数据库初始化脚本引用，提供标准表结构定义。
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_capabilities (
    agent_id      TEXT PRIMARY KEY,                               -- Agent 唯一标识（如 AKO_chat）
    description   TEXT NOT NULL DEFAULT '',                       -- 能力描述
    keywords      TEXT NOT NULL DEFAULT '[]',                     -- JSON 数组: 匹配关键词
    input_schema  TEXT NOT NULL DEFAULT '{}',                     -- JSON: 输入参数 schema
    output_schema TEXT NOT NULL DEFAULT '{}',                     -- JSON: 输出参数 schema
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),        -- ISO-8601 创建时间
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))         -- ISO-8601 更新时间
);

-- 索引: 按更新时间排序（用于能力变更发现）
CREATE INDEX IF NOT EXISTS idx_capabilities_updated
    ON agent_capabilities(updated_at DESC);
