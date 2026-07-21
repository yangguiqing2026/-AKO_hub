"""
AKO Hub — 意图路由模块。

将用户自然语言输入解析为 Agent 调用计划，支持：
1. 关键词匹配路由
2. Agent 能力语义匹配
3. 复合任务 DAG 编排
4. 路由规则 YAML 热加载

文档编号: AGE-TECH-AKO-HUB-021 §Router
"""

from .intent_router import IntentRouter
from .task_executor import TaskNode, TaskExecutor

__all__ = ["IntentRouter", "TaskNode", "TaskExecutor"]
