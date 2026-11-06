"""
记忆存储 (SQLite) + 冲突消解
============================
- 持久化: 跨会话记忆迁移的物理基础 —— 进程重启后记忆仍在
- 冲突消解: 同槽位新记忆写入时, 旧条目不删除而是归档(superseded_by 链)。
  归档记忆默认不参与检索 —— "现在住哪"不会再答旧地址;
  但保留时序, "以前住哪"类问题仍可查(审计/时序问答)。
- 可关闭: store(resolve_conflicts=False) 供消融实验。
"""

import os
import sqlite3

from .models import MemoryItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    slot TEXT NOT NULL,
    value TEXT NOT NULL,
    tier TEXT NOT NULL,
    source_session TEXT,
    created_at REAL,
    last_used REAL,
    superseded_by TEXT,
    evidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_slot ON memories(slot);
CREATE INDEX IF NOT EXISTS idx_active ON memories(superseded_by);
"""


class MemoryStore:
    def __init__(self, db_path: str = ":memory:", resolve_conflicts: bool = True):
        self.db_path = db_path
        self.resolve_conflicts = resolve_conflicts
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")  # 读写并发不互斥
        self.conn.execute("PRAGMA busy_timeout=5000")  # 多连接下等锁而非报错
        self._migrate()

    def _migrate(self) -> None:
        """schema 版本迁移: 旧库自动补列/建表 —— 升级不丢数据。"""
        self.conn.executescript(_SCHEMA)
        ver_row = (
            self.conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
            if self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_meta'"
            ).fetchone()
            else None
        )
        version = int(ver_row[0]) if ver_row else 1
        # 未来 schema 变更在此按 version 逐级迁移:
        # if version < 2: self.conn.execute("ALTER TABLE ..."); version = 2
        self.conn.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute(
            "INSERT INTO _meta VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(version),),
        )
        self.conn.commit()

    # ---------- 写入 ----------

    def add(self, item: MemoryItem) -> dict:
        """写入一条记忆; 同槽位存在活跃记忆时触发冲突消解。返回动作报告。"""
        action: dict = {"action": "added", "slot": item.slot, "value": item.value, "superseded": []}
        if self.resolve_conflicts:
            for old in self.active(slot=item.slot):
                if old.value != item.value:
                    old.superseded_by = item.id
                    self.conn.execute(
                        "UPDATE memories SET superseded_by=? WHERE id=?", (item.id, old.id)
                    )
                    action["superseded"].append({"id": old.id, "value": old.value})
                else:
                    # 完全相同的记忆: 丢弃重复, 保留旧的(避免膨胀)
                    action["action"] = "duplicate"
                    return action
        self.conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?)",
            (
                item.id,
                item.slot,
                item.value,
                item.tier,
                item.source_session,
                item.created_at,
                item.last_used,
                None,
                item.evidence or item.text,
            ),
        )
        self.conn.commit()
        return action

    # ---------- 读取 ----------

    def active(self, slot: str | None = None) -> list[MemoryItem]:
        """所有活跃(未被归档且未过期)记忆。"""
        q = (
            "SELECT id,slot,value,tier,source_session,created_at,last_used,superseded_by,evidence "
            "FROM memories WHERE superseded_by IS NULL"
        )
        args: tuple = ()
        if slot:
            q += " AND slot=?"
            args = (slot,)
        return [self._row(r) for r in self.conn.execute(q, args)]

    def all(self, include_archived: bool = False) -> list[MemoryItem]:
        q = (
            "SELECT id,slot,value,tier,source_session,created_at,last_used,"
            "superseded_by,evidence FROM memories"
        )
        if not include_archived:
            q += " WHERE superseded_by IS NULL"
        return [self._row(r) for r in self.conn.execute(q)]

    def history(self, slot: str) -> list[MemoryItem]:
        """某槽位的版本链(含归档), 按时间序 —— 时序问答用。"""
        rows = self.conn.execute(
            "SELECT id,slot,value,tier,source_session,created_at,last_used,"
            "superseded_by,evidence FROM memories WHERE slot=? ORDER BY created_at",
            (slot,),
        )
        return [self._row(r) for r in rows]

    def touch(self, ids: list[str], now_ts: float | None = None):
        """检索命中 → 更新 last_used (新近度信号)。"""
        now_ts = now_ts if now_ts is not None else __import__("time").time()
        self.conn.executemany(
            "UPDATE memories SET last_used=? WHERE id=?", [(now_ts, i) for i in ids]
        )
        self.conn.commit()

    def n_items(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    # ---------- 内部 ----------

    @staticmethod
    def _row(r) -> MemoryItem:
        it = MemoryItem.__new__(MemoryItem)
        (
            it.id,
            it.slot,
            it.value,
            it.tier,
            it.source_session,
            it.created_at,
            it.last_used,
            it.superseded_by,
            it.evidence,
        ) = r
        it.text = f"{it.slot}={it.value}"
        it.score = 0.0
        return it
