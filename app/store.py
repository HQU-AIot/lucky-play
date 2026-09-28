"""SQLite 存储层。

单进程部署，用 RLock + BEGIN IMMEDIATE 保证抽奖扣库存的原子性，
并发请求不会把同一件奖品发出去两次。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .lottery import DYNAMIC_PER_WIN, PrizeSpec

DEFAULT_PRIZES = [
    # id, 名称, emoji, 基础权重, 总库存（来自 docs/spec/奖品清单.jpg + NFC 纪念卡）
    ("lollipop", "不二家棒棒糖", "🍭", 30, 53),
    ("nailong", "奶龙手办", "🐲", 20, 36),
    ("notebook", "口袋笔记本", "📓", 15, 18),
    ("nfccard", "NFC纪念卡", "🪪", 12, 10),
    ("bookmark", "油画书签", "🎨", 10, 8),
    ("shark", "鲨鱼匕首", "🦈", 8, 6),
    ("crawlpet", "电子爬宠", "🦎", 6, 4),
    ("gamesir", "盖世小鸡手柄", "🎮", 2, 1),
]

DEFAULT_CONFIG = {
    "thanks_weight": "9",
    "dynamic_enabled": "1",
    "dynamic_mode": DYNAMIC_PER_WIN,
    "win_stop_at": "5.5",
    "event_name": "幸运抽奖",
    "event_date": "2026-09-30",
    "event_note": "国庆前一天 · 好运相逢",
}

DEFAULT_ADMIN_TOKEN = "123456"

CONFIG_KEYS = set(DEFAULT_CONFIG)


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in (
                    """CREATE TABLE IF NOT EXISTS prizes (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        emoji TEXT NOT NULL DEFAULT '🎁',
                        sort INTEGER NOT NULL DEFAULT 0,
                        base_weight REAL NOT NULL DEFAULT 0,
                        total_stock INTEGER NOT NULL DEFAULT 0,
                        remaining INTEGER NOT NULL DEFAULT 0
                    )""",
                    """CREATE TABLE IF NOT EXISTS config (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS draws (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        result TEXT NOT NULL,
                        prize_id TEXT,
                        prize_name TEXT
                    )""",
                ):
                    self._conn.execute(stmt)
                # 播种 + 幂等迁移：空库按清单顺序全量播种；已有库只补默认清单里
                # 新增的奖品，sort 追加到末尾顺延（不与已有项撞号，展示顺序稳定）。
                # 已有奖品的权重/库存一概不动——现场调过的参数保持原样。
                existing = {r["id"] for r in self._conn.execute("SELECT id FROM prizes")}
                next_sort = self._conn.execute(
                    "SELECT COALESCE(MAX(sort) + 1, 0) FROM prizes"
                ).fetchone()[0]
                for i, (pid, name, emoji, weight, stock) in enumerate(DEFAULT_PRIZES):
                    if pid in existing:
                        continue
                    sort = i if not existing else next_sort
                    next_sort += 1
                    self._conn.execute(
                        "INSERT INTO prizes (id, name, emoji, sort, base_weight,"
                        " total_stock, remaining) VALUES (?,?,?,?,?,?,?)",
                        (pid, name, emoji, sort, weight, stock, stock),
                    )
                for key, value in DEFAULT_CONFIG.items():
                    self._conn.execute(
                        "INSERT OR IGNORE INTO config (key, value) VALUES (?,?)", (key, value)
                    )
                self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    # ---- 查询 ----

    def list_prizes(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM prizes ORDER BY sort, id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_config(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def specs(self) -> list[PrizeSpec]:
        return [
            PrizeSpec(
                id=p["id"],
                name=p["name"],
                base_weight=float(p["base_weight"]),
                total=int(p["total_stock"]),
                remaining=int(p["remaining"]),
            )
            for p in self.list_prizes()
        ]

    def history(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM draws ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(prize_id, 'thanks') AS key,
                       COUNT(*) AS count
                FROM draws GROUP BY key
                """
            ).fetchall()
            total_row = self._conn.execute("SELECT COUNT(*) AS n FROM draws").fetchone()
        by_prize = {r["key"]: r["count"] for r in rows}
        return {"total_draws": int(total_row["n"]), "by_prize": by_prize}

    # ---- 抽奖（原子扣库存） ----

    def draw(self, rng, prize_eff: dict[str, float], thanks_eff: float) -> dict:
        """在同一事务里完成：锁定库存 → 抽取 → 扣减 → 落记录。

        权重由调用方在事务外预计算（权重变化不涉及超卖问题），
        库存扣减在本事务内，保证 remaining 不为负、不超卖。

        已接受的瞬态偏差：权重基于事务外的库存快照。若并发请求恰在
        某奖品被抽空的同一瞬间到达，该单抽仍按快照权重计算（本应转移
        给谢谢参与的质量未及时转移）。窗口为微秒级、下一抽自愈、绝不
        超卖；默认权重下偏差 ≤0.6 个百分点，单机 kiosk 场景可忽略。
        """
        from .lottery import pick_result

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT id, name, emoji, remaining, total_stock FROM prizes"
                ).fetchall()
                stock = {r["id"]: dict(r) for r in rows}
                usable_eff = {
                    pid: w
                    for pid, w in prize_eff.items()
                    if w > 0 and stock.get(pid, {}).get("remaining", 0) > 0
                }
                outcome = pick_result(rng, usable_eff, thanks_eff)
                prize = None
                if outcome != "thanks" and outcome is not None:
                    row = stock[outcome]
                    self._conn.execute(
                        "UPDATE prizes SET remaining = remaining - 1 WHERE id = ?",
                        (outcome,),
                    )
                    prize = {
                        "id": outcome,
                        "name": row["name"],
                        "emoji": row["emoji"],
                        "remaining": int(row["remaining"]) - 1,
                        "total": int(row["total_stock"]),
                    }
                self._conn.execute(
                    "INSERT INTO draws (ts, result, prize_id, prize_name) VALUES (?,?,?,?)",
                    (
                        datetime.now().astimezone().isoformat(timespec="seconds"),
                        "thanks" if prize is None else "prize",
                        prize["id"] if prize else None,
                        prize["name"] if prize else None,
                    ),
                )
                self._conn.execute("COMMIT")
                return {"result": "prize" if prize else "thanks", "prize": prize}
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    # ---- 后台写入 ----

    def set_config(self, updates: dict[str, str]) -> None:
        unknown = set(updates) - CONFIG_KEYS
        if unknown:
            raise ValueError(f"未知配置项: {sorted(unknown)}")
        with self._lock:
            self._conn.executemany(
                "INSERT INTO config (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, str(v)) for k, v in updates.items()],
            )

    def set_weights(self, weights: dict[str, float], thanks_weight: float | None) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for pid, w in weights.items():
                    self._conn.execute(
                        "UPDATE prizes SET base_weight = ? WHERE id = ?", (float(w), pid)
                    )
                if thanks_weight is not None:
                    self._conn.execute(
                        "INSERT INTO config (key, value) VALUES ('thanks_weight', ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(float(thanks_weight)),),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def set_stock(self, prize_id: str, remaining: int, total: int | None = None) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE prizes SET remaining = ?,"
                " total_stock = COALESCE(?, total_stock)"
                " WHERE id = ? RETURNING remaining, total_stock",
                (int(remaining), int(total) if total is not None else None, prize_id),
            )
            row = cur.fetchone()
            self._conn.commit()
        return dict(row) if row else None

    def reset_history(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM draws")

    def replenish_all(self) -> None:
        with self._lock:
            self._conn.execute("UPDATE prizes SET remaining = total_stock")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
