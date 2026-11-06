"""核心功能测试: 抽取 / 冲突消解 / 分级遗忘 / 检索 / 评测集冒烟。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from memagent.agent import MemoryAssistant
from memagent.extract import RuleExtractor
from memagent.forget import Forgetter
from memagent.models import MemoryItem
from memagent.retrieve import Retriever
from memagent.store import MemoryStore

# ---------- 抽取 ----------


def test_extract_basic_slots():
    ex = RuleExtractor()
    items = ex.extract("你好, 我叫小林, 我住在杭州, 平时喝拿铁。", "s1")
    slots = {i.slot: i.value for i in items}
    assert slots["name"] == "小林"
    assert slots["city"] == "杭州"
    assert slots["drink"] == "拿铁"


def test_extract_update_vs_state():
    ex = RuleExtractor()
    items = ex.extract("我搬到上海了, 咖啡改喝美式了。", "s3")
    slots = {i.slot: i.value for i in items}
    assert slots["city"] == "上海"
    assert slots["drink"] == "美式"


def test_extract_pet_normalization():
    ex = RuleExtractor()
    items = ex.extract("我养了一只金毛。", "s2")
    assert any(i.slot == "pet" and i.value == "金毛" for i in items)


def test_extract_no_false_positive_on_job():
    ex = RuleExtractor()
    items = ex.extract("我在字节跳动上班。", "s2")
    slots = {i.slot for i in items}
    assert "city" not in slots  # 不能把公司名当城市
    assert "job" in slots


def test_extract_allergy():
    ex = RuleExtractor()
    items = ex.extract("我对花生过敏。", "s1")
    assert any(i.slot == "allergy" and i.value == "花生" for i in items)
    assert all(i.tier == "pinned" for i in items if i.slot == "allergy")


# ---------- 冲突消解 ----------


def test_conflict_supersedes_and_archives():
    asst = MemoryAssistant()
    asst.chat("s1", "我住在杭州。")
    asst.chat("s3", "我搬到上海了。")
    r = asst.ask("我现在住哪个城市?")
    assert r["answer"] == "上海"
    r2 = asst.ask("我以前住哪个城市?")
    assert r2["answer"] == "杭州"  # 版本链保留旧值


def test_no_conflict_keeps_both():
    asst = MemoryAssistant(resolve_conflicts=False)
    asst.chat("s1", "我住在杭州。")
    asst.chat("s3", "我搬到上海了。")
    cities = [i.value for i in asst.store.active(slot="city")]
    assert sorted(cities) == ["上海", "杭州"]  # 两个都活跃 → 检索有歧义


def test_duplicate_not_readded():
    asst = MemoryAssistant()
    asst.chat("s1", "我住在杭州。")
    n1 = asst.stats()["n_total"]
    asst.chat("s2", "我住在杭州。")
    assert asst.stats()["n_total"] == n1


# ---------- 分级遗忘 ----------


def test_pinned_never_expires():
    store = MemoryStore()
    a = MemoryItem("allergy", "花生", "s1")
    a.created_at = a.last_used = 0.0  # 极老
    store.add(a)
    expired = Forgetter().sweep(store, now_ts=1000 * 86400.0)
    assert expired == []
    assert len(store.active()) == 1


def test_ephemeral_expires():
    store = MemoryStore()
    e = MemoryItem("drink", "拿铁", "s1")
    e.tier = "ephemeral"
    e.created_at = e.last_used = 0.0
    store.add(e)
    expired = Forgetter().sweep(store, now_ts=10 * 86400.0)
    assert len(expired) == 1


# ---------- 检索 ----------


def test_retriever_slot_prior():
    r = Retriever()
    a = MemoryItem("city", "杭州", "s1")
    b = MemoryItem("pet", "金毛", "s1")
    top = r.top("我现在住哪个城市?", [a, b])
    assert top[0].slot == "city"


# ---------- 评测集冒烟 ----------


def test_bench_smoke():
    from memagent.eval.bench import run_bench

    res = run_bench(n_scenarios=6)
    assert 0.0 <= res["full"]["acc_overall"] <= 1.0
    assert res["full"]["n_probes"] > 0


def test_schema_version_recorded():
    store = MemoryStore()
    ver = store.conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    assert ver and int(ver[0]) >= 1


def test_wal_mode_active():

    store = MemoryStore()
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] in ("wal", "memory")
