#!/usr/bin/env python3
"""
hub/cli/dispatch.py
AKO Hub 路由器 CLI

用法:
    python -m hub.cli.dispatch --action create --agent AKO_new_agent
    python -m hub.cli.dispatch --action rework --agent AKO_pack_agent
    python -m hub.cli.dispatch --action delete --agent AKO_old_agent --confirm
    python -m hub.cli.dispatch --action status --agent ALL
    
危险操作（rework/delete/create ALL）需要 --confirm 二次确认
"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

import sys as _sys
from pathlib import Path
from datetime import datetime

# 路径计算：AKO_hub/cli/dispatch.py → AKO_hub → D:/AKO
_HERE = Path(__file__).resolve().parent
AKO_HUB_DIR = _HERE.parent  # AKO_hub/
AKO_ROOT = AKO_HUB_DIR.parent  # D:/AKO
if str(AKO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(AKO_ROOT))

from AKO_hub.events.schemas import BaseEvent, EventType
from AKO_hub.events.bus import EventBus
from tools.validate_permission import validate


STATE_FILE = AKO_ROOT / "pipeline_state.json"

DANGEROUS_ACTIONS = {
    ("create", "ALL"): "将创建所有缺失的 Agent，确认?",
    ("rework", "ALL"): "将对所有 Agent 触发返修，确认?",
    ("delete", None): "将删除 Agent，此操作不可撤销，确认?",
}


class HubDispatcher:
    def __init__(self):
        self.bus = EventBus()
    
    def dispatch(self, action: str, agent: str, confirmed: bool = False, **kwargs) -> bool:
        """
        路由分发：根据 action 和 agent 执行对应操作
        
        action: create | rework | delete | status | hold_resolve | unblock
        agent: Agent ID 或 "ALL"
        """
        # 1. 校验 Agent 存在性
        if agent != "ALL":
            agent_dir = AKO_ROOT / agent
            if not agent_dir.exists() and action != "create":
                print(f"[Error] Agent '{agent}' does not exist at {agent_dir}")
                registry_dir = AKO_ROOT / "AKO_registry_agent"
                if registry_dir.exists():
                    print(f"[Info] Run 'python -m AKO_registry_agent.main --query {agent}' to check registry")
                return False
        
        # 2. 危险操作二次确认
        danger_key = (action, agent if agent == "ALL" else None)
        if danger_key in DANGEROUS_ACTIONS and not confirmed:
            msg = DANGEROUS_ACTIONS[danger_key]
            print(f"[DANGER] {msg}")
            print("[DANGER] Add --confirm flag to proceed.")
            return False
        
        # 3. 权限校验
        who = kwargs.get("who", "developer")
        if action in ("create", "rework", "delete"):
            allowed, reason = validate(who, "write", f"{agent}/" if agent != "ALL" else "pipeline_state.json")
            if not allowed:
                print(f"[Permission Denied] {reason}")
                return False
        
        # 4. 执行操作
        handler = getattr(self, f"_do_{action}", None)
        if not handler:
            print(f"[Error] Unknown action: {action}")
            return False
        
        return handler(agent, **kwargs)
    
    def _do_create(self, agent: str, **kwargs) -> bool:
        """创建新 Agent：调用 hook_create_agent"""
        if agent == "ALL":
            print("[TODO] ALL creation not implemented in MVP")
            return False
        
        category = kwargs.get("category", "general")
        author = kwargs.get("author", "AKO Team")
        
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "tools.hook_create_agent", 
             "--name", agent, "--category", category, "--author", author],
            cwd=str(AKO_ROOT),
            capture_output=True,
            text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        return result.returncode == 0
    
    def _do_rework(self, agent: str, **kwargs) -> bool:
        """触发返修：将 Agent 状态重置到 S2，重新执行 QC"""
        state = self._load_state()
        
        targets = [agent] if agent != "ALL" else list(state.get("agents", {}).keys())
        
        for target in targets:
            if target not in state.get("agents", {}):
                print(f"[Skip] Agent '{target}' not registered")
                continue
            
            # 更新状态
            state["agents"][target]["state"] = "S2_qc_in_progress"
            state["agents"][target]["rework_count"] = state["agents"][target].get("rework_count", 0) + 1
            state["agents"][target]["last_updated"] = datetime.utcnow().isoformat()
            
            # 发送事件
            event = BaseEvent(
                event_type=EventType.STATE_TRANSITION,
                source_agent="hub.dispatch",
                version="1.0"
            )
            event_data = event.model_dump()
            event_data["agent_id"] = target
            event_data["from_state"] = "*"
            event_data["to_state"] = "S2_qc_in_progress"
            event_data["reason"] = "REWORK_TRIGGERED"
            self.bus.emit(BaseEvent(**event_data))
            
            print(f"[OK] Agent '{target}' marked for rework → S2_qc_in_progress")
        
        self._save_state(state)
        return True
    
    def _do_delete(self, agent: str, **kwargs) -> bool:
        """删除 Agent：删除目录 + 从 state 中移除"""
        agent_dir = AKO_ROOT / agent
        if agent_dir.exists():
            import shutil
            shutil.rmtree(agent_dir)
            print(f"[OK] Deleted directory: {agent_dir}")
        
        state = self._load_state()
        if agent in state.get("agents", {}):
            del state["agents"][agent]
            self._save_state(state)
            print(f"[OK] Removed '{agent}' from pipeline_state")
        
        return True
    
    def _do_status(self, agent: str, **kwargs) -> bool:
        """查询状态"""
        state = self._load_state()
        
        if agent == "ALL":
            for aid, info in state.get("agents", {}).items():
                print(f"  {aid}: {info.get('state', 'S1_init')} (updated: {info.get('last_updated', 'N/A')})")
        else:
            info = state.get("agents", {}).get(agent, {})
            print(json.dumps(info, indent=2, ensure_ascii=False))
        
        return True
    
    def _do_hold_resolve(self, agent: str, **kwargs) -> bool:
        """解除人工门禁"""
        from AKO_pipeline_agent.core.human_review_gate import HumanReviewGate
        gate = HumanReviewGate()
        gate.resolve_hold(agent, kwargs.get("approver", "admin"), kwargs.get("resolution", ""))
        return True
    
    def _do_unblock(self, agent: str, **kwargs) -> bool:
        """解除 Guardian 阻断"""
        from AKO_cluster_guardian_agent.auto_blocker import Guardian
        guardian = Guardian()
        guardian.unblock(agent, kwargs.get("reason", ""))
        return True
    
    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {}
    
    def _save_state(self, state: dict):
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)


def main():
    parser = argparse.ArgumentParser(description="AKO Hub Dispatcher")
    parser.add_argument("--action", required=True, 
                       choices=["create", "rework", "delete", "status", "hold_resolve", "unblock"],
                       help="Action to perform")
    parser.add_argument("--agent", required=True, help="Target agent ID or 'ALL'")
    parser.add_argument("--confirm", action="store_true", help="Confirm dangerous actions")
    parser.add_argument("--category", default="general", help="Agent category (for create)")
    parser.add_argument("--author", default="AKO Team", help="Author name")
    parser.add_argument("--approver", default="admin", help="Approver (for hold_resolve)")
    parser.add_argument("--resolution", default="", help="Resolution note")
    parser.add_argument("--reason", default="", help="Reason (for unblock)")
    
    args = parser.parse_args()
    
    dispatcher = HubDispatcher()
    success = dispatcher.dispatch(
        action=args.action,
        agent=args.agent,
        confirmed=args.confirm,
        category=args.category,
        author=args.author,
        approver=args.approver,
        resolution=args.resolution,
        reason=args.reason
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
