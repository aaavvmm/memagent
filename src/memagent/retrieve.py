"""
检索: BM25 式词频匹配 × 新近度 × 重要性(分层)
==============================================
score = bm25 × (1 + w_rec·recency) × (1 + w_tier·tier_boost) × slot_match_boost

可关闭各分量(消融): w_rec=0 关新近度, tier_boost=0 关分层。
槽位直配 boost: 问题里出现"住/住哪"直接命中 city 槽 —— 模拟真实系统中
槽位元数据对检索的强先验, 也是消融里"纯文本检索 vs 结构化检索"的对照。
"""

import math
import re
import time

from .models import MemoryItem

TIER_BOOST = {"pinned": 0.5, "normal": 0.0, "ephemeral": -0.2}

# 问题词 → 槽位先验(中文检索的实用设计: 问题里 explicit 问"住哪"就该查 city)
QUESTION_SLOTS = {
    "住": "city",
    "住在": "city",
    "搬家": "city",
    "城市": "city",
    "喝": "drink",
    "咖啡": "drink",
    "奶茶": "drink",
    "饮品": "drink",
    "养": "pet",
    "猫": "pet",
    "狗": "pet",
    "宠物": "pet",
    "过敏": "allergy",
    "忌口": "allergy",
    "叫什么": "name",
    "名字": "name",
    "工作": "job",
    "上班": "job",
    "跳槽": "job",
    "生日": "birthday",
    "喜欢": "preference",
    "讨厌": "dislike",
    "生病": "health",
    "不舒服": "health",
}


def _tokens(text: str) -> list[str]:
    """中文 bigram + 单字 + ascii 词: 轻量分词, 无外部依赖。"""
    text = text.lower()
    out = re.findall(r"[a-z0-9]+", text)
    han = re.findall(r"[一-龥]", text)
    out += [a + b for a, b in zip(han, han[1:], strict=False)]  # bigram 主力
    out += han  # 单字兜底
    return out


class Retriever:
    def __init__(
        self,
        w_rec: float = 0.3,
        w_tier: float = 1.0,
        slot_boost: float = 3.0,
        half_life_days: float = 14.0,
    ):
        self.w_rec = w_rec
        self.w_tier = w_tier
        self.slot_boost = slot_boost
        self.half_life = half_life_days

    def score(self, query: str, item: MemoryItem, now_ts: float | None = None) -> float:
        now_ts = now_ts if now_ts is not None else time.time()
        qt, it_ = set(_tokens(query)), set(_tokens(item.text))
        # BM25-lite: 查询词命中率 × 惰性 idf(命中 rare bigram 权重更高)
        if not qt:
            return 0.0
        hits = qt & it_
        if not hits:
            base = 0.0
        else:
            idf = sum(1.0 / math.log(2 + len(h)) for h in hits)
            base = idf / sum(1.0 / math.log(2 + len(h)) for h in qt)
        # 新近度: 指数半衰期
        age_d = max(0.0, (now_ts - item.last_used) / 86400)
        rec = 0.5 ** (age_d / self.half_life)
        # 槽位先验
        qslots = {s for k, s in QUESTION_SLOTS.items() if k in query}
        sb = self.slot_boost if item.slot in qslots else 1.0
        # 分层
        tb = 1.0 + self.w_tier * TIER_BOOST.get(item.tier, 0.0)
        return base * (1 + self.w_rec * rec) * sb * tb

    def top(
        self, query: str, items: list[MemoryItem], k: int = 4, now_ts: float | None = None
    ) -> list[MemoryItem]:
        now_ts = now_ts if now_ts is not None else time.time()
        for it in items:
            it.score = self.score(query, it, now_ts)
        items.sort(key=lambda x: -x.score)
        return items[:k]
