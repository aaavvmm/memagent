# -*- coding: utf-8 -*-
"""
记忆抽取器: 对话文本 → 槽位化记忆候选
====================================
RuleExtractor 用中文模式规则做确定性抽取 —— 评测隔离的关键设计:
记忆系统的好坏(存储/冲突/遗忘/检索)与 NLU 好坏解耦, 消融实验才干净。
LLMExtractor 提供同样的槽位接口(可选接入任意 API), 生产用法见 README。

注意边界: 规则抽取对句式有要求(城市用"住在/搬到"、宠物用"养了"),
真实开放对话用 LLMExtractor —— 这是刻意的分层设计, 见 README"设计取舍"。
"""
import re

from .models import MemoryItem

# 模式: (槽位, 正则)。更新类在前, 陈述类在后(同值重复会被 store 去重)。
PATTERNS = [
    # ---- 更新类(同槽位旧值触发归档) ----
    ("city",       r"(?:搬到|搬去)(?P<v>[一-龥]{2,6})(?:了|住了?|生活)?"),
    ("drink",      r"(?:改喝|换成|改点)(?P<v>[一-龥]{1,5})(?:了)?"),
    ("preference", r"(?:现在|最近)(?:更)?喜欢(?P<v>[一-龥A-Za-z0-9]{1,8})(?:了)?"),
    ("job",        r"(?:换工作(?:了|到)|跳槽到?|入职)(?:了)?(?P<v>[一-龥A-Za-z0-9（）()]{2,15})"),
    # ---- 陈述类 ----
    ("name",       r"(?:我(?:的名字)?(?:叫|是)|叫我|名字是)(?P<v>[一-龥A-Za-z]{1,10})(?:,|。|谢谢|$)"),
    ("city",       r"(?:我)?(?:住在|生活在)(?P<v>[一-龥]{2,6})(?:市|区)?"),
    ("allergy",    r"我(?:对)(?P<v>[一-龥]{1,8})(?:过敏|不耐受)"),
    ("pet",        r"我(?:养了?|领养了?)(?:一只|只)?(?P<v>[一-龥]{1,6})(?:了)?"),
    ("drink",      r"(?:我)?(?:平时|一般|经常|喜欢|爱)?喝(?P<v>[一-龥]{1,5})(?:,|。|$)"),
    ("preference", r"我(?:很|比较|特别|最)?喜欢(?P<v>[一-龥A-Za-z0-9]{1,8})(?:了)?"),
    ("dislike",    r"我(?:不|不太|不怎么)喜欢(?P<v>[一-龥A-Za-z0-9]{1,8})"),
    ("job",        r"我(?:在|是)(?P<v>[一-龥A-Za-z0-9（）()]{2,15}?)(?:上班|工作|任职|做研究|教书)"),
    ("birthday",   r"(?:我的生日是|我生日)(?P<v>[0-9年月日]{4,12})"),
    ("plan",       r"(?:今天|这周末?|明天)(?:我)?(?:想|打算|要去)(?P<v>[一-龥A-Za-z0-9]{1,8})"),
    ("health",     r"我(?:得了?|查出|有)(?P<v>[一-龥]{1,8})(?:的病|病|症状|问题)?(?:,|。|$)"),
]

# 值清洗: 去句尾语气词/标点
_STRIP = r"[了哦呢吧。\s，,]$"


def _clean(v: str) -> str:
    v = v.strip()
    for _ in range(2):
        v = re.sub(_STRIP, "", v)
    return v


class RuleExtractor:
    """确定性规则抽取器。extract(text, session) → [MemoryItem]"""

    name = "rule"

    def extract(self, text: str, session: str) -> list[MemoryItem]:
        items, seen = [], set()
        for slot, pat in PATTERNS:
            for mtc in re.finditer(pat, text):
                v = _clean(mtc.group("v"))
                if not v or len(v) > 12:
                    continue
                if slot == "preference" and v.startswith("喝"):
                    continue        # "喜欢喝拿铁"归 drink, 不留 preference=喝拿铁
                if slot == "drink" and re.search(r"养|过敏|搬到", mtc.group(0)):
                    continue
                key = (slot, v)
                if key in seen:
                    continue
                seen.add(key)
                items.append(MemoryItem(slot, v, session, text=text))
        return items


class LLMExtractor:
    """LLM 抽取适配器(占位): 生产中用 prompt 抽槽位 JSON, 接口与 RuleExtractor 一致。
    本项目评测用规则抽取以保证确定性, 见 README。"""

    name = "llm"

    def __init__(self, chat_fn):
        self.chat_fn = chat_fn   # callable(prompt) -> str

    def extract(self, text: str, session: str) -> list[MemoryItem]:
        import json as _json
        prompt = ("从下面对话中抽取关于用户的长期记忆, 输出JSON数组 [{slot,value}], "
                  f"slot ∈ name/city/allergy/pet/drink/preference/dislike/job/birthday/health。\n对话: {text}")
        data = _json.loads(self.chat_fn(prompt))
        return [MemoryItem(d["slot"], d["value"], session, text=text) for d in data]
