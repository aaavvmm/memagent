"""
记忆条目模型
============
设计要点:
  - 槽位(slot)化: 每条记忆归约到 {槽位: 值}, 冲突消解变成同槽位新旧替换 ——
    可判定、可评测, 也是 Mem0/ChatGPT memory 等系统的内部抽象
  - 版本链: 旧值不删除而是 superseded_by 归档, 保留"曾经是什么"(可审计,
    支撑"以前喜欢拿铁"类时序问答)
  - 分层(tier): pinned(过敏等安全事实, 永不遗忘) / normal(偏好事实, 慢衰减)
    / ephemeral(临时上下文, 快衰减) —— 遗忘策略按层定制
"""

import time
import uuid

# 记忆分层 → 遗忘时间常数(天); pinned 为 None 表示不衰减
TIER_TAU = {"pinned": None, "normal": 30.0, "ephemeral": 3.0}

# 槽位 → 默认分层 (安全/健康类事实必须 pinned, 临时计划 ephemeral)
SLOT_TIER = {
    "allergy": "pinned",
    "health": "pinned",
    "name": "pinned",
    "birthday": "pinned",
    "plan": "ephemeral",
}

# 常驻上下文的安全槽位(主动提醒用; name/birthday 虽 pin 但不做提醒)
SAFETY_SLOTS = {"allergy", "health"}


class MemoryItem:
    __slots__ = (
        "id",
        "slot",
        "value",
        "tier",
        "source_session",
        "created_at",
        "last_used",
        "score",
        "superseded_by",
        "text",
        "evidence",
    )

    def __init__(
        self, slot: str, value: str, source_session: str, text: str = "", tier: str | None = None
    ):
        self.id = uuid.uuid4().hex[:8]
        self.slot = slot
        self.value = value
        self.text = text or f"{slot}={value}"
        self.tier = tier or SLOT_TIER.get(slot, "normal")
        self.source_session = source_session
        self.created_at = time.time()
        self.last_used = self.created_at
        self.score = 1.0  # 检索时动态计算
        self.superseded_by: str | None = None
        self.evidence = text  # 原句(来源可审计)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slot": self.slot,
            "value": self.value,
            "tier": self.tier,
            "source_session": self.source_session,
            "created_at": self.created_at,
            "superseded_by": self.superseded_by,
            "text": self.text,
        }


def now() -> float:
    return time.time()
