"""
记忆评测器 + 消融实验
====================
实验一(标准): 70 场景 × 5 类探测, 准确率 + staleness
实验二(长期): 20 场景 × 270 天演化, 考 pinned 保护 / 冲突链 / 存储有界性
消融: full / no_conflict / no_forget / no_tier
输出: 终端表格 + eval_results.json(供简历数字引用)
"""

import json
import sys

from ..agent import MemoryAssistant
from .scenarios import SESSION_DAYS, build, build_longterm

ABLATIONS = {
    "full": {},
    "no_conflict": {"resolve_conflicts": False},
    "no_forget": {"forget": False},
    "no_tier": {"tier_aware": False},
}

SESSION_DAYS_L = {f"L{i}": i * 30.0 for i in range(10)}


def _clock_factory():
    """评测用虚拟时钟, 会话按天推进。"""
    state = {"day": 0.0}
    return (lambda: state["day"] * 86400.0), state.__setitem__


def _run(sc, days_map: dict, probe_day: float, **assistant_kwargs) -> dict:
    clock, set_day = _clock_factory()
    asst = MemoryAssistant(clock=clock, **assistant_kwargs)
    for sess, text in sc.events:
        set_day("day", days_map[sess])
        asst.chat(sess, text)
    set_day("day", probe_day)

    per_type: dict = {}
    stale = 0
    for p in sc.probes:
        r = asst.ask(p.question)
        ok = r["answer"] == p.expected
        t = per_type.setdefault(p.qtype, {"n": 0, "ok": 0})
        t["n"] += 1
        t["ok"] += ok
        # staleness: 答了旧值(答案出现在记忆列表/历史里)而非"不知道"
        if not ok and r["answer"] is not None:
            hist = [m["value"] for m in r["memories"]]
            if r["answer"] in hist:
                stale += 1
    return {"per_type": per_type, "stale": stale, "n_memories": asst.stats()["n_total"]}


def run_scenario(sc, **kwargs) -> dict:
    return _run(sc, SESSION_DAYS, SESSION_DAYS["s4"] + 5, **kwargs)


def run_bench(n_scenarios: int = 70, seed: int = 7, ablations: list[str] | None = None) -> dict:
    ablations = ablations or list(ABLATIONS)
    scenarios = build(n_scenarios, seed)
    out = {}
    for name in ablations:
        agg: dict = {}
        stale_n = mem_sum = 0
        for sc in scenarios:
            r = run_scenario(sc, **ABLATIONS[name])
            for t, d in r["per_type"].items():
                a = agg.setdefault(t, {"n": 0, "ok": 0})
                a["n"] += d["n"]
                a["ok"] += d["ok"]
            stale_n += r["stale"]
            mem_sum += r["n_memories"]
        total_n = sum(a["n"] for a in agg.values())
        total_ok = sum(a["ok"] for a in agg.values())
        out[name] = {
            "acc_by_type": {t: round(a["ok"] / a["n"], 3) for t, a in sorted(agg.items())},
            "acc_overall": round(total_ok / total_n, 3),
            "n_probes": total_n,
            "stale_rate": round(stale_n / total_n, 3),
            "avg_memories_per_scenario": round(mem_sum / len(scenarios), 1),
        }
    return out


def run_longterm(n_scenarios: int = 20, seed: int = 11) -> dict:
    """270 天演化实验: pinned 保护 / 冲突链 / 存储有界性。"""
    scenarios = build_longterm(n_scenarios, seed)
    out = {}
    for name, kwargs in (
        ("full", ABLATIONS["full"]),
        ("no_forget", ABLATIONS["no_forget"]),
        ("no_tier", ABLATIONS["no_tier"]),
    ):
        agg: dict = {}
        mem_sum = 0
        for sc in scenarios:
            r = _run(sc, SESSION_DAYS_L, 275.0, **kwargs)
            for t, d in r["per_type"].items():
                a = agg.setdefault(t, {"n": 0, "ok": 0})
                a["n"] += d["n"]
                a["ok"] += d["ok"]
            mem_sum += r["n_memories"]
        out[name] = {
            "acc_by_type": {t: round(a["ok"] / a["n"], 3) for t, a in sorted(agg.items())},
            "acc_allergy": agg.get("LT-allergy", {"ok": 0})["ok"]
            / max(1, agg.get("LT-allergy", {"n": 1})["n"]),
            "avg_memories": round(mem_sum / len(scenarios), 1),
        }
        out[name]["acc_allergy"] = round(out[name]["acc_allergy"], 3)
    return out


def print_report(results: dict, title: str):
    names = list(results)
    types = sorted({t for r in results.values() for t in r["acc_by_type"]})
    print(f"\n━━ {title} " + "━" * max(0, 50 - len(title)))
    hdr = (
        f"{'配置':<12}"
        + "".join(f"{t:>11}" for t in types)
        + f"{'总体':>8}{'过时率':>8}{'均记忆数':>9}"
    )
    print(hdr)
    for name in names:
        r = results[name]
        row = f"{name:<12}" + "".join(
            f"{r['acc_by_type'].get(t, float('nan')):>11.0%}" for t in types
        )
        if "acc_overall" in r:
            row += (
                f"{r['acc_overall']:>8.0%}{r['stale_rate']:>8.0%}"
                f"{r['avg_memories_per_scenario']:>9.1f}"
            )
        else:
            row += f"{'':>8}{'':>8}{r['avg_memories']:>9.1f}"
        print(row)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 70
    res = {"standard": run_bench(n_scenarios=n), "longterm": run_longterm()}
    print_report(res["standard"], f"标准评测 ({n} 场景, 4 会话, 40 天)")
    print_report(res["longterm"], "长期演化 (20 场景, 10 会话, 270 天)")
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\n已保存 eval_results.json")
