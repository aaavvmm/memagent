# -*- coding: utf-8 -*-
"""
分级遗忘
========
真实记忆系统的取舍: 全部记住 → 检索噪声涨、存储无界; 全部过期 → 丢安全信息。
本模块按 tier 差异化:
  pinned    永不遗忘(过敏/健康/姓名/生日) —— 安全设计
  normal    τ=30天 慢衰减(偏好/事实)
  ephemeral τ=3天  快衰减(临时上下文)
衰减语义: age > τ·2 且 低使用 → 过期(可物理清除); 只是"淡忘"不清除,
靠检索的新近度降权实现 —— 与人类记忆的"可得性 vs 可用性"区分一致。

消融开关: sweep(decay=False) 关遗忘 → 展示存储无界增长 + 检索噪声。
"""
import time

from .models import TIER_TAU
from .store import MemoryStore


class Forgetter:
    def __init__(self, enabled: bool = True, usage_keep: int = 2):
        self.enabled = enabled
        self.usage_keep = usage_keep   # last_used 距今多少个 τ 内仍算"在用"

    def sweep(self, store: MemoryStore, now_ts: float | None = None) -> list[str]:
        """返回本次过期清除的 id 列表。pinned 永不清除。"""
        if not self.enabled:
            return []
        now_ts = now_ts if now_ts is not None else time.time()   # 0.0 是合法虚拟时钟
        expired = []
        for it in store.active():
            tau = TIER_TAU.get(it.tier)
            if tau is None:            # pinned
                continue
            age_d = (now_ts - it.created_at) / 86400
            idle_d = (now_ts - it.last_used) / 86400
            if age_d > tau * 2 and idle_d > tau:
                expired.append(it.id)
        if expired:
            store.conn.executemany(
                "DELETE FROM memories WHERE id=?", [(i,) for i in expired])
            store.conn.commit()
        return expired
