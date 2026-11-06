"""
一键演示: "真正记得你的助理" 三幕剧
====================================
第一幕 s1: 自我介绍 → 看助理记住了什么
第二幕 s3: 搬家+换咖啡 → 看冲突消解("已更新, 旧值归档")
第三幕 s4: 隔了 30 天回来问问题 → 看跨会话记忆与时序问答
最后: 打开记忆面板(每条记忆带来源/时间/版本链/钉住标记)
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from memagent.agent import MemoryAssistant

DAY = 86400.0
state = {"day": 0}


def clock():
    return state["day"] * DAY


def say(asst, session, text):
    r = asst.chat(session, text)
    print(f"  [{session}] 你: {text}")
    for a in r["remembered"]:
        old = (
            f" (更新: {a['slot']} 旧值「{a['superseded'][0]['value']}」已归档)"
            if a["superseded"]
            else ""
        )
        print(f"        助理: 📌 我记住了 {a['slot']} = {a['value']}{old}")
    if r["expired"]:
        print(f"        助理: 🧹 清理了 {len(r['expired'])} 条过期记忆")


def ask(asst, q):
    r = asst.ask(q)
    print(f"  你: {q}")
    print(
        f"        助理: {r['answer'] or '(我不记得这个)'}"
        f"   [依据: {r['slot']} 槽位, 引用 {len(r['memories'])} 条记忆]"
    )
    # pinned(安全类)记忆常驻上下文: 相关场景主动提醒
    for m in r["memories"]:
        if m.get("always") and m["slot"] != r["slot"]:
            print(f"        助理: ⚠️ 顺带提醒(安全类记忆常驻): {m['slot']} = {m['value']}")


def main():
    asst = MemoryAssistant(clock=clock)
    print("=" * 62)
    print("第一幕 · 第 1 天: 自我介绍")
    print("=" * 62)
    say(asst, "s1", "你好, 我叫小林, 住在杭州, 平时喝拿铁。")
    say(asst, "s1", "对了, 我对花生过敏。")

    print("\n" + "=" * 62)
    print("第二幕 · 第 10 天: 搬家 + 换咖啡 (冲突消解)")
    print("=" * 62)
    say(asst, "s3", "我搬到上海了, 咖啡改喝美式了。")

    print("\n" + "=" * 62)
    print("第三幕 · 第 45 天: 隔一个月回来 (跨会话记忆 + 时序问答)")
    print("=" * 62)
    state["day"] = 45
    ask(asst, "我现在住哪个城市?")  # → 上海 (新值)
    ask(asst, "我以前住哪个城市?")  # → 杭州 (版本链)
    ask(asst, "我现在喝什么?")  # → 美式
    ask(asst, "点咖啡时有什么要注意的?")  # → 花生过敏 (pinned 永不忘)
    ask(asst, "我叫什么名字?")  # → 小林

    print("\n" + "=" * 62)
    print("记忆面板 (每条记忆: 值/来源/证据原句/版本数, 📍=pinned)")
    print("=" * 62)
    for m in asst.memory_panel():
        pin = "📍" if m["pinned"] else "  "
        print(
            f"  {pin} {m['slot']:<11} = {m['value']:<6} "
            f"[{m['source_session']} 录入, 版本×{m['versions']}] 证据: {m['evidence'][:24]}…"
        )
    print(f"\n统计: {asst.stats()}")


if __name__ == "__main__":
    main()
