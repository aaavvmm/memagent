"""
自建中文记忆评测集: 场景生成器
==============================
设计(与既有记忆基准 LOLComms/MemBench 的差异):
  - 全中文多会话, 每个场景 = 3 个事实会话 + 1 个探测会话
  - 5 类探测, 每类针对记忆系统的一个具体能力:
      T1 直接回忆   单会话内陈述, 后会话探测
      T2 跨会话迁移 隔多个会话+干扰对话后探测
      T3 冲突更新   旧值被新值覆盖, 探测"现在" → 考冲突消解
      T4 时序/安全  "以前住哪"考版本链; 过敏probe考 pinned 保护
      T5 槽位推断   "养了一只金毛" → 宠物=金毛, 考值归一化
  - 评测只打记忆系统: 抽取用确定性规则, 探测答案为槽位精确匹配
  - seed 固定 → 完全可复现
"""

import random
from dataclasses import dataclass, field

DRINKS = ["拿铁", "美式", "摩卡", "龙井", "普洱", "气泡水", "乌龙茶", "果汁"]
CITIES = ["杭州", "上海", "北京", "深圳", "成都", "广州", "武汉", "南京"]
PETS = ["金毛", "柯基", "布偶猫", "橘猫", "柴犬", "英短", "仓鼠", "兔子"]
ALLERGIES = ["花生", "芒果", "海鲜", "花粉", "鸡蛋", "青霉素"]
JOBS = [
    ("字节跳动", "上班"),
    ("腾讯", "工作"),
    ("华为", "上班"),
    ("一家中学", "教书"),
    ("研究所", "做研究"),
]
PREFS = ["摄影", "徒步", "科幻电影", "羽毛球", "做饭", "滑雪"]
DISLIKES = ["香菜", "恐怖片", "加班", "剧本杀"]
NAMES = ["小林", "阿哲", "晓雯", "志强", "雨桐", "大白"]
HEALTHS = ["胃炎", "高血压", "腰椎间盘突出"]
PLANS = ["去健身房", "看电影", "加班", "爬山", "回家吃饭", "剪头发"]

SESSION_DAYS = {"s1": 0, "s2": 3, "s3": 10, "s4": 40}


@dataclass
class Probe:
    qtype: str  # T1..T5
    question: str
    expected: str  # 槽位值精确匹配
    slot: str


@dataclass
class Scenario:
    sid: str
    events: list[tuple[str, str]] = field(default_factory=list)  # (session, utterance)
    probes: list[Probe] = field(default_factory=list)


FILLER = [
    "今天天气不错, 心情挺好。",
    "最近在忙一个项目, 挺累的。",
    "周末去逛了逛商场。",
    "昨晚看了场球赛, 很精彩。",
]


def make_scenario(rng: random.Random, sid: str) -> Scenario:
    sc = Scenario(sid)
    name = rng.choice(NAMES)
    city1, city2 = rng.sample(CITIES, 2)
    drink1, drink2 = rng.sample(DRINKS, 2)
    pet = rng.choice(PETS)
    allergy = rng.choice(ALLERGIES)
    job, verb = rng.choice(JOBS)
    pref = rng.choice(PREFS)
    dislike = rng.choice(DISLIKES)

    # ---- s1: 基础事实(名字/城市/饮品/宠物/过敏) ----
    e1 = [f"你好, 我叫{name}。", f"我住在{city1}。", f"我平时喝{drink1}。"]
    has_allergy = rng.random() < 0.7
    if has_allergy:
        e1.append(f"我对{allergy}过敏。")
    # ---- s2: 干扰会话(偏好/工作/宠物, 与 s1 事实无关) ----
    e2 = [
        f"我最近喜欢{pref}。",
        f"我在{job}{verb}。",
        f"我养了一只{pet}。",
        f"我不太喜欢{dislike}。",
    ]
    # ---- s3: 更新会话(城市迁移/饮品更换) ----
    e3 = [f"我搬到{city2}了。", f"我改喝{drink2}了。"]
    # ---- s4: 探测会话(只寒暄) ----
    e4 = ["好久不见!"]

    for sess, evs in (("s1", e1), ("s2", e2), ("s3", e3), ("s4", e4)):
        for t in evs:
            sc.events.append((sess, t))
        sc.events.append((sess, rng.choice(FILLER)))
        sc.events.append((sess, f"这周末我打算{rng.choice(PLANS)}。"))  # ephemeral 噪声

    # ---- 探测集 ----
    sc.probes += [
        Probe("T1", "我叫什么名字?", name, "name"),
        Probe("T2", "我还记得吗, 我在哪儿上班?", job, "job"),
        Probe("T2", "我平时喜欢什么爱好?", pref, "preference"),
        Probe("T3", "我现在住哪个城市?", city2, "city"),
        Probe("T3", "我现在喝什么?", drink2, "drink"),
        Probe("T4", "我以前住哪个城市?", city1, "city"),
        Probe("T5", "我的宠物是什么?", pet, "pet"),
    ]
    if has_allergy:  # 与事件同一次抽签 —— 事件与探测严格配对
        sc.probes.append(Probe("T4", "我对什么过敏?", allergy, "allergy"))
    return sc


def build(n_scenarios: int = 70, seed: int = 7) -> list[Scenario]:
    rng = random.Random(seed)
    return [make_scenario(rng, f"sc{i:03d}") for i in range(n_scenarios)]


# ================= 长期演化实验 =================
# 10 个会话横跨 270 天: 城市/饮品每 30 天更新一次, 过敏只在第 0 天说过一次,
# 每个会话夹一条 ephemeral 计划。考三件事:
#   ① pinned 保护: 过敏记忆在 270 天后是否还在(关分层 → 被遗忘清除)
#   ② 冲突链: "现在住哪" 须答最后一个城市
#   ③ 存储有界性: 遗忘开启时 ephemeral 被清扫, 关闭时无界增长


def make_longterm(rng: random.Random, sid: str) -> Scenario:
    sc = Scenario(sid)
    allergy = rng.choice(ALLERGIES)
    n_sess = 10
    cities = [rng.choice(CITIES) for _ in range(n_sess)]
    drinks = [rng.choice(DRINKS) for _ in range(n_sess)]
    for i in range(n_sess):
        sess = f"L{i}"
        sc.events.append((sess, f"我搬到{cities[i]}了。" if i else f"我住在{cities[i]}。"))
        sc.events.append((sess, f"我改喝{drinks[i]}了。" if i else f"我平时喝{drinks[i]}。"))
        if i == 0:
            sc.events.append((sess, f"我对{allergy}过敏。"))
        sc.events.append((sess, f"今天我打算{rng.choice(PLANS)}。"))
    final_city, final_drink = cities[-1], drinks[-1]
    sc.probes = [
        Probe("LT-allergy", "我对什么过敏?", allergy, "allergy"),
        Probe("LT-city", "我现在住哪个城市?", final_city, "city"),
        Probe("LT-drink", "我现在喝什么?", final_drink, "drink"),
    ]
    return sc


def build_longterm(n: int = 20, seed: int = 11) -> list[Scenario]:
    rng = random.Random(seed)
    return [make_longterm(rng, f"lt{i:03d}") for i in range(n)]
