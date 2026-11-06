"""
MemoryAssistant —— 应用外壳: 多会话私人助理
===========================================
职责: 编排 抽取→存储(冲突消解)→遗忘→检索 四个内核组件;
对用户暴露两件事:
  chat():  说话, 返回"我记住了..."与被引用的记忆(记忆面板的实时反馈)
  ask():   记忆问答 —— 评测的入口, 也是真实使用的检索接口
  memory_panel(): 记忆面板数据(值/来源/时间/版本链, 可查可改可删)

virtual clock 可注入(clock 参数): 评测里会话间隔以"天"推进,
真实使用传默认系统时钟 —— 同一套代码两种时间语义。
"""

import json
import logging
import sys
import time

from .extract import RuleExtractor
from .forget import Forgetter
from .models import SAFETY_SLOTS
from .retrieve import QUESTION_SLOTS, Retriever
from .store import MemoryStore

PAST_HINTS = ("以前", "之前", "原来", "过去", "曾经", "上一次")

log = logging.getLogger("memagent")
if not log.handlers:  # JSON 行日志走 stderr —— stdout 可能是协议/交互通道
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)


def _jlog(event: str, **kw) -> None:
    log.info(json.dumps({"event": event, **kw}, ensure_ascii=False))


class MemoryAssistant:
    def __init__(
        self,
        db_path: str = ":memory:",
        extractor=None,
        retriever: Retriever | None = None,
        resolve_conflicts: bool = True,
        forget: bool = True,
        tier_aware: bool = True,
        slot_boost: float = 3.0,
        clock=time.time,
    ):
        self.clock = clock
        self.store = MemoryStore(db_path, resolve_conflicts=resolve_conflicts)
        self.extractor = extractor or RuleExtractor()
        self.retriever = retriever or Retriever(slot_boost=slot_boost)
        self.forgetter = Forgetter(enabled=forget)
        self.tier_aware = tier_aware  # 消融开关: False → 全部按 normal 层(安全事实失去保护)
        self.events: list[dict] = []  # 会话事件日志(报告/审计)

    # ---------- 主流程 ----------

    def chat(self, session: str, text: str) -> dict:
        items = self.extractor.extract(text, session)
        for it in items:
            it.created_at = it.last_used = self.clock()  # 统一虚拟时钟(评测可注入)
        if not self.tier_aware:
            for it in items:
                it.tier = "normal"
        actions = [self.store.add(it) for it in items]
        expired = self.forgetter.sweep(self.store, now_ts=self.clock())
        ranked = self.retriever.top(text, self.store.active(), now_ts=self.clock())
        # 只有真正相关的命中才刷新 last_used —— 零分"陪跑"不续命,
        # 否则所有记忆都会被闲聊永久保鲜, 遗忘机制失效
        hits = [c for c in ranked if c.score > 0.05]
        if hits:
            self.store.touch([c.id for c in hits], now_ts=self.clock())
        remembered = [a for a in actions if a["action"] == "added"]
        result = {
            "remembered": remembered,
            "expired": expired,
            "context": [c.to_dict() for c in ranked],
        }
        self.events.append(
            {"session": session, "text": text, "remembered": remembered, "expired": expired}
        )
        for a in remembered:
            _jlog(
                "memory_added",
                session=session,
                slot=a["slot"],
                value=a["value"],
                superseded=len(a["superseded"]),
            )
        if expired:
            _jlog("memories_expired", session=session, n=len(expired))
        return result

    def ask(self, question: str) -> dict:
        """记忆问答。返回 {answer, slot, memories}。
        "以前/之前"类时序问题走版本链查归档值; 其余查活跃记忆。"""
        past = any(k in question for k in PAST_HINTS)
        qslots = list({s for k, s in QUESTION_SLOTS.items() if k in question})
        if past and qslots:
            return self._ask_past(question, qslots[0])
        ranked = self.retriever.top(question, self.store.active(), now_ts=self.clock())
        self.store.touch([c.id for c in ranked if c.score > 0.05], now_ts=self.clock())
        hit = next((it for it in ranked if it.slot in qslots), None)
        if not hit and qslots:  # 无词法命中时按槽位直查(兜底)
            cands = self.store.active(slot=qslots[0])
            hit = cands[-1] if cands else None
        # pinned(安全类)记忆常驻上下文: 与问题无关也带上 —— 点单场景主动浮现过敏
        mems = [c.to_dict() for c in ranked[:4]]
        for m in mems:
            if m["tier"] == "pinned" and m["slot"] in SAFETY_SLOTS:
                m["always"] = True
        in_ids = {m["id"] for m in mems}
        mems += [
            p.to_dict() | {"always": True}
            for p in self.store.active()
            if p.tier == "pinned" and p.slot in SAFETY_SLOTS and p.id not in in_ids
        ]
        return {
            "answer": hit.value if hit else None,
            "slot": hit.slot if hit else (qslots[0] if qslots else None),
            "memories": mems,
        }

    def _ask_past(self, question: str, slot: str) -> dict:
        hist = self.store.history(slot)
        superseded = [h for h in hist if h.superseded_by]
        old = superseded[0] if superseded else (hist[0] if len(hist) > 1 else None)
        return {
            "answer": old.value if old else None,
            "slot": slot,
            "memories": [h.to_dict() for h in hist],
        }

    # ---------- 记忆面板(应用外壳的"看得见"部分) ----------

    def memory_panel(self) -> list[dict]:
        out = []
        for it in sorted(
            self.store.active(), key=lambda x: {"pinned": 0, "normal": 1}.get(x.tier, 2)
        ):
            hist = self.store.history(it.slot)
            out.append(
                {
                    "slot": it.slot,
                    "value": it.value,
                    "tier": it.tier,
                    "source_session": it.source_session,
                    "evidence": it.evidence,
                    "versions": len(hist),
                    "pinned": it.tier == "pinned",
                }
            )
        return out

    def edit_memory(self, slot: str, value: str, session: str = "user_edit") -> dict:
        """用户手工修正 —— 走与对话抽取相同的冲突消解通道。"""
        from .models import MemoryItem

        it = MemoryItem(slot, value, session, text=f"(手工修正) {slot}={value}")
        it.created_at = it.last_used = self.clock()
        return self.store.add(it)

    def delete_memory(self, item_id: str) -> bool:
        cur = self.store.conn.execute("DELETE FROM memories WHERE id=?", (item_id,))
        self.store.conn.commit()
        return cur.rowcount > 0

    # ---------- 统计 ----------

    def stats(self) -> dict:
        tiers: dict[str, int] = {}
        for it in self.store.all(include_archived=True):
            tiers[it.tier] = tiers.get(it.tier, 0) + 1
        return {
            "n_total": self.store.n_items(),
            "n_active": len(self.store.active()),
            "tiers": tiers,
            "n_events": len(self.events),
        }
