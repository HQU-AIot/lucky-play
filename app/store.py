"""SQLite 存储层。

单进程部署，用 RLock + BEGIN IMMEDIATE 保证抽奖扣库存的原子性，
并发请求不会把同一件奖品发出去两次。
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
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
    "slot_diamond_weight": "10",
    "slot_gamesir_enabled": "1",
    "slot_jackpot_enabled": "1",
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
        # 双钻自选的一次性凭据 {token: 签发时刻}；确认/过期后移除。
        # 单进程部署，内存即可——凭据丢失的最坏结果是这轮双钻作废，不涉库存。
        self._pending: dict[str, float] = {}
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
                # v2 迁移：老虎机独立权重列。老库回填为转盘权重（行为不变），
                # 之后两套权重各自调节互不影响
                prize_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(prizes)")}
                if "slot_weight" not in prize_cols:
                    self._conn.execute("ALTER TABLE prizes ADD COLUMN slot_weight REAL")
                self._conn.execute(
                    "UPDATE prizes SET slot_weight = base_weight WHERE slot_weight IS NULL"
                )
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
                        " slot_weight, total_stock, remaining) VALUES (?,?,?,?,?,?,?,?)",
                        (pid, name, emoji, sort, weight, weight, stock, stock),
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

    def specs(self, use_slot_weight: bool = False) -> list[PrizeSpec]:
        """奖品快照。use_slot_weight=True 时 base_weight 字段承载老虎机权重
        （两套权重独立调节，转盘/老虎机各自计算有效概率）。"""
        col = "slot_weight" if use_slot_weight else "base_weight"
        return [
            PrizeSpec(
                id=p["id"],
                name=p["name"],
                base_weight=float(p[col]),
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

    def draw_slot(
        self,
        rng,
        prize_eff: dict[str, float],
        diamond_weight: float,
        gamesir_enabled: bool,
        jackpot_enabled: bool,
    ) -> dict:
        """老虎机三轴对对碰：同一事务里抽符号 → 定奖 → 逐件扣减 → 逐件落记录。

        规则（产品口径）：
        - 三轴全不同 = 没抽到（谢谢参与）；
        - 两同 = 该奖品 ×1（库存不足 2 时的三同也只发 1）；
        - 三同普通奖品 = 该奖品 ×2；
        - 三同手柄 = 手柄 ×1 + 任选一件其它奖品（系统随机）；
        - 三同钻石 = 超级大奖：除手柄外每类奖品各 ×1（仅发仍有库存的类别），
          超级大奖开关关闭时该组合重抽；
        - 两同钻石 = 中奖者现场自选：本事务只圈出可选清单（有库存的非手柄
          奖品）并签发一次性凭据、零扣减零流水，等 choose_pending() 确认；
        - 两同 = ×1（手柄单件库存恰好发 1 件；2026-09-30 按需求取消"两同手柄重抽"）。
        除双钻自选外，其余"任选"都在事务内由系统随机决定并逐件写流水。
        """
        from .lottery import DIAMOND, slot_outcome, slot_pool, slot_spin

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT id, name, emoji, remaining, total_stock FROM prizes"
                ).fetchall()
                stock = {r["id"]: dict(r) for r in rows}
                # 池内按事务内库存复筛（与 store.draw 的 usable_eff 口径一致：
                # 快照后恰被并发抽空的奖品不再出现在轴面组合里）
                pool = {
                    pid: w
                    for pid, w in slot_pool(prize_eff, diamond_weight, gamesir_enabled).items()
                    if pid == DIAMOND or stock.get(pid, {}).get("remaining", 0) > 0
                }
                ts = datetime.now().astimezone().isoformat(timespec="seconds")
                symbols: list[str] = []
                wins: list[str] = []
                result = "thanks"
                pending_token: str | None = None
                pending_choices: list[dict] | None = None
                for _ in range(300):
                    if not pool:
                        break
                    symbols = slot_spin(rng, pool)
                    kind, sym = slot_outcome(symbols)
                    if kind == "mixed":
                        break
                    if kind == "pair":
                        if sym == DIAMOND:
                            # 双钻 = 中奖者现场自选：这里只圈出可选清单（有库存的
                            # 非手柄奖品，与权重无关）并签发一次性凭据，等玩家在
                            # 自选框里点「确认领取」时由 choose_pending() 扣库存
                            avail = [
                                pid
                                for pid, row in stock.items()
                                if pid != "gamesir" and row["remaining"] > 0
                            ]
                            if avail:
                                pending_token = secrets.token_urlsafe(16)
                                pending_choices = [
                                    {"id": pid, "name": stock[pid]["name"], "emoji": stock[pid]["emoji"]}
                                    for pid in avail
                                ]
                            break
                        # 两同 = ×1（含手柄：单件库存恰好发这 1 件，2026-09-30 按需求取消重抽）
                        wins = [sym] * min(1, int(stock[sym]["remaining"]))
                        result = "prize"
                        break
                    # triple
                    if sym == DIAMOND:
                        if not jackpot_enabled:
                            continue
                        # 超级大奖：除手柄外每类有库存的奖品各 ×1（与权重无关）
                        wins = [
                            pid
                            for pid, row in stock.items()
                            if pid != "gamesir" and row["remaining"] > 0
                        ]
                        if wins:
                            result = "prize"
                        break
                    if sym == "gamesir":
                        other = [
                            pid
                            for pid, row in stock.items()
                            if pid != "gamesir"
                            and pid != DIAMOND
                            and row["remaining"] > 0
                        ]
                        wins = ["gamesir"] + ([rng.choice(other)] if other else [])
                        result = "prize"
                        break
                    wins = [sym] * min(2, int(stock[sym]["remaining"]))
                    result = "prize"
                    break

                if pending_token:
                    # 双钻自选：本轮不扣库存不落流水，等确认（choose_pending）。
                    # 顺带清理过期凭据（30 分钟未确认作废）
                    now = time.monotonic()
                    self._pending = {
                        t: ts for t, ts in self._pending.items() if now - ts < 1800
                    }
                    self._pending[pending_token] = now
                    self._conn.execute("COMMIT")
                    return {
                        "result": "choose",
                        "symbols": symbols,
                        "pending": pending_token,
                        "choices": pending_choices,
                        "game": "slot",
                    }

                granted = []
                for pid in wins:
                    row = stock[pid]
                    if row["remaining"] <= 0:
                        continue  # 超级大奖口径：只发仍有库存的类别
                    self._conn.execute(
                        "UPDATE prizes SET remaining = remaining - 1 WHERE id = ? AND remaining > 0",
                        (pid,),
                    )
                    row["remaining"] -= 1
                    granted.append(pid)
                    self._conn.execute(
                        "INSERT INTO draws (ts, result, prize_id, prize_name) VALUES (?,?,?,?)",
                        (ts, "prize", pid, row["name"]),
                    )
                if not granted:
                    self._conn.execute(
                        "INSERT INTO draws (ts, result, prize_id, prize_name) VALUES (?,?,?,?)",
                        (ts, "thanks", None, None),
                    )
                self._conn.execute("COMMIT")
                prizes = [
                    {
                        "id": pid,
                        "name": stock[pid]["name"],
                        "emoji": stock[pid]["emoji"],
                        "remaining": int(stock[pid]["remaining"]),
                        "total": int(stock[pid]["total_stock"]),
                    }
                    for pid in granted
                ]
                return {
                    "result": "prize" if granted else "thanks",
                    "prize": prizes[0] if prizes else None,
                    "prizes": prizes,
                    "symbols": symbols,
                    "game": "slot",
                }
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def choose_pending(self, token: str, prize_id: str | None) -> dict:
        """双钻自选的确认端：凭据一次性，事务内扣库存、落流水。

        prize_id 为 None（或玩家把可选奖品耗尽后点"收下谢谢参与"）= 记一条
        谢谢参与。凭据无效/已用返回 error；选中的奖品若刚被并发抽走，返回
        error 且凭据仍有效，玩家可换一件再确认——库存永远不会被扣成负数。
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                now = time.monotonic()
                self._pending = {
                    t: ts for t, ts in self._pending.items() if now - ts < 1800
                }
                if token not in self._pending:
                    self._conn.execute("COMMIT")
                    return {"error": "这次选择已失效，请重新抽一次", "expired": True}
                ts = datetime.now().astimezone().isoformat(timespec="seconds")
                if prize_id is None:
                    self._conn.execute(
                        "INSERT INTO draws (ts, result, prize_id, prize_name) VALUES (?,?,?,?)",
                        (ts, "thanks", None, None),
                    )
                    self._conn.execute("COMMIT")
                    del self._pending[token]  # COMMIT 成功后才消费：异常路径下库存/流水/凭据始终一致
                    return {"result": "thanks", "prize": None, "prizes": [], "game": "slot"}
                row = self._conn.execute(
                    "SELECT id, name, emoji, remaining, total_stock FROM prizes WHERE id = ?",
                    (prize_id,),
                ).fetchone()
                if row is None or prize_id == "gamesir" or row["remaining"] <= 0:
                    # 不消费凭据：玩家换一件仍可确认
                    self._conn.execute("COMMIT")
                    return {"error": "手慢了，这件奖品刚被抽走，换一件吧"}
                self._conn.execute(
                    "UPDATE prizes SET remaining = remaining - 1 WHERE id = ? AND remaining > 0",
                    (prize_id,),
                )
                self._conn.execute(
                    "INSERT INTO draws (ts, result, prize_id, prize_name) VALUES (?,?,?,?)",
                    (ts, "prize", prize_id, row["name"]),
                )
                self._conn.execute("COMMIT")
                del self._pending[token]  # COMMIT 成功后才消费（见上）
                prize = {
                    "id": prize_id,
                    "name": row["name"],
                    "emoji": row["emoji"],
                    "remaining": int(row["remaining"]) - 1,
                    "total": int(row["total_stock"]),
                }
                return {
                    "result": "prize",
                    "prize": prize,
                    "prizes": [prize],
                    "game": "slot",
                }
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

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

    def set_weights(
        self,
        weights: dict[str, float],
        thanks_weight: float | None,
        slot_weights: dict[str, float] | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for pid, w in weights.items():
                    self._conn.execute(
                        "UPDATE prizes SET base_weight = ? WHERE id = ?", (float(w), pid)
                    )
                for pid, w in (slot_weights or {}).items():
                    self._conn.execute(
                        "UPDATE prizes SET slot_weight = ? WHERE id = ?", (float(w), pid)
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
