"""SQLite 存储层（Inventory 协议的默认实现，见 app/inventory.py）。

单进程部署，用 RLock + BEGIN IMMEDIATE 保证抽奖扣库存的原子性，
并发请求不会把同一件奖品发出去两次。
"""

from __future__ import annotations

import json
import math
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

# 种子清单里属于"终极大奖"的奖品：不进转盘、双钻自选与三钻超级大奖都不含它。
# 运行时的同一语义由 prizes.is_grand 列承载，这里是播种/迁移的初始值。
DEFAULT_GRAND_IDS = frozenset({"gamesir"})

DEFAULT_CONFIG = {
    "thanks_weight": "9",
    "dynamic_enabled": "1",
    "dynamic_mode": DYNAMIC_PER_WIN,
    "win_stop_at": "5.5",
    "slot_diamond_weight": "10",
    "slot_grand_enabled": "1",
    "slot_jackpot_enabled": "1",
    "event_name": "幸运抽奖",
    "event_date": "2026-09-30",
    "event_note": "国庆前一天 · 好运相逢",
}

DEFAULT_ADMIN_TOKEN = "123456"

# 奖品 id 保留字：thanks=谢谢参与哨兵、diamond=老虎机钻石符号。
# 撞车会让该奖品永远无法被抽中或权重被系统符号覆盖（评审确认的真实缺陷）。
RESERVED_PRIZE_IDS = frozenset({"thanks", "diamond"})

CONFIG_KEYS = set(DEFAULT_CONFIG)


def load_seed(prizes_file: Path | str | None) -> list[tuple]:
    """解析播种清单：给定 JSON 文件则用之，否则用 DEFAULT_PRIZES。

    返回统一 7 元组列表 (id, name, emoji, base_weight, slot_weight, total, is_grand)。
    JSON 条目字段：id/name/emoji/base_weight/total_stock 必填（emoji 可省略），
    slot_weight、is_grand 可省（分别默认等于 base_weight、False）。
    """
    if not prizes_file:
        return [
            (pid, name, emoji, w, w, stock, pid in DEFAULT_GRAND_IDS)
            for pid, name, emoji, w, stock in DEFAULT_PRIZES
        ]
    path = Path(prizes_file)
    if not path.is_file():
        raise FileNotFoundError(f"LUCKY_PRIZES_JSON 指向的文件不存在: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"奖品清单 JSON 解析失败（{path}）: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"奖品清单 JSON 应为非空数组（{path}）")
    items: list[tuple] = []
    seen_ids: set[str] = set()
    for i, ent in enumerate(raw):
        if not isinstance(ent, dict):
            raise ValueError(f"奖品清单第 {i + 1} 项应为对象: {ent!r}")
        pid = ent.get("id")
        name = ent.get("name")
        if not isinstance(pid, str) or not (1 <= len(pid) <= 32):
            raise ValueError(f"奖品清单第 {i + 1} 项 id 非法（1-32 字符）: {pid!r}")
        if pid in seen_ids:
            raise ValueError(f"奖品清单第 {i + 1} 项 id 重复: {pid!r}")
        if pid in RESERVED_PRIZE_IDS:
            raise ValueError(f"奖品清单第 {i + 1} 项 id 是保留字（thanks/diamond）: {pid!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"奖品清单第 {i + 1} 项 name 非法: {name!r}")
        emoji = ent.get("emoji") or "🎁"
        base_w = ent.get("base_weight", 0)
        slot_w = ent.get("slot_weight", base_w)
        total = ent.get("total_stock", 0)
        # isfinite 拦 Infinity（json.loads 接受该非标字面量，inf 落库会毒化全部
        # 概率计算——与管理 API 的 allow_inf_nan=False 防线对齐）；NaN 由
        # not (v >= 0) 一并拒绝
        if not all(
            isinstance(v, (int, float))
            and v >= 0
            and math.isfinite(v)
            for v in (base_w, slot_w)
        ):
            raise ValueError(f"奖品 {pid} 的权重须为非负有限数值")
        if not isinstance(total, int) or total < 0:
            raise ValueError(f"奖品 {pid} 的 total_stock 须为非负整数")
        seen_ids.add(pid)
        items.append((pid, name.strip(), emoji, float(base_w), float(slot_w),
                      total, bool(ent.get("is_grand", False))))
    return items


class Store:
    def __init__(self, db_path: Path, prizes_file: Path | str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._seed = load_seed(prizes_file)
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
                # v3 迁移：终极大奖标志列（语义见 DEFAULT_GRAND_IDS 注释）。
                # 仅在列刚创建时执行一次性补标；此后管理员经 CRUD 改的标志不被覆盖
                if "is_grand" not in prize_cols:
                    self._conn.execute(
                        "ALTER TABLE prizes ADD COLUMN is_grand INTEGER NOT NULL DEFAULT 0"
                    )
                    seed_grand = {p[0] for p in self._seed if p[6]}
                    if seed_grand:
                        marks = ",".join("?" for _ in seed_grand)
                        self._conn.execute(
                            f"UPDATE prizes SET is_grand = 1 WHERE id IN ({marks})",
                            tuple(seed_grand),
                        )
                # v3 配置键迁移：slot_gamesir_enabled → slot_grand_enabled（值原样保留）
                old = self._conn.execute(
                    "SELECT value FROM config WHERE key = 'slot_gamesir_enabled'"
                ).fetchone()
                if old is not None:
                    self._conn.execute(
                        "INSERT INTO config (key, value) VALUES ('slot_grand_enabled', ?)"
                        " ON CONFLICT(key) DO NOTHING",
                        (old["value"],),
                    )
                    self._conn.execute("DELETE FROM config WHERE key = 'slot_gamesir_enabled'")
                # 播种 + 幂等迁移：空库按清单顺序全量播种；已有库只补清单里
                # 新增的奖品，sort 追加到末尾顺延（不与已有项撞号，展示顺序稳定）。
                # 已有奖品的权重/库存/标志一概不动——现场调过的参数保持原样。
                existing = {r["id"] for r in self._conn.execute("SELECT id FROM prizes")}
                next_sort = self._conn.execute(
                    "SELECT COALESCE(MAX(sort) + 1, 0) FROM prizes"
                ).fetchone()[0]
                for i, (pid, name, emoji, base_w, slot_w, stock, is_grand) in enumerate(self._seed):
                    if pid in existing:
                        continue
                    sort = i if not existing else next_sort
                    next_sort += 1
                    self._conn.execute(
                        "INSERT INTO prizes (id, name, emoji, sort, base_weight,"
                        " slot_weight, total_stock, remaining, is_grand)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, name, emoji, sort, base_w, slot_w, stock, stock,
                         1 if is_grand else 0),
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
        grand_enabled: bool,
        jackpot_enabled: bool,
    ) -> dict:
        """老虎机三轴对对碰：同一事务里抽符号 → 定奖 → 逐件扣减 → 逐件落记录。

        规则（产品口径，"大奖"= prizes.is_grand 标记的终极大奖）：
        - 三轴全不同 = 没抽到（谢谢参与）；
        - 两同 = 该奖品 ×1（库存不足 2 时的三同也只发 1）；
        - 三同普通奖品 = 该奖品 ×2；
        - 三同大奖 = 大奖 ×1 + 任选一件其它奖品（系统随机）；
        - 三同钻石 = 超级大奖：除大奖外每类奖品各 ×1（仅发仍有库存的类别），
          超级大奖开关关闭时该组合重抽；
        - 两同钻石 = 中奖者现场自选：本事务只圈出可选清单（有库存的非大奖
          奖品）并签发一次性凭据、零扣减零流水，等 choose_pending() 确认；
        - 两同 = ×1（大奖单件库存恰好发 1 件；2026-09-30 按需求取消"两同大奖重抽"）。
        除双钻自选外，其余"任选"都在事务内由系统随机决定并逐件写流水。
        """
        from .lottery import DIAMOND, slot_outcome, slot_pool, slot_spin

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT id, name, emoji, remaining, total_stock, is_grand FROM prizes"
                ).fetchall()
                stock = {r["id"]: dict(r) for r in rows}
                grand_ids = {pid for pid, row in stock.items() if row["is_grand"]}
                # 池内按事务内库存复筛（与 store.draw 的 usable_eff 口径一致：
                # 快照后恰被并发抽空的奖品不再出现在轴面组合里）
                pool = {
                    pid: w
                    for pid, w in slot_pool(
                        prize_eff, diamond_weight, grand_ids, grand_enabled
                    ).items()
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
                            # 非大奖奖品，与权重无关）并签发一次性凭据，等玩家在
                            # 自选框里点「确认领取」时由 choose_pending() 扣库存
                            avail = [
                                pid
                                for pid, row in stock.items()
                                if not row["is_grand"] and row["remaining"] > 0
                            ]
                            if avail:
                                pending_token = secrets.token_urlsafe(16)
                                pending_choices = [
                                    {"id": pid, "name": stock[pid]["name"], "emoji": stock[pid]["emoji"]}
                                    for pid in avail
                                ]
                            break
                        # 两同 = ×1（含大奖：单件库存恰好发这 1 件，2026-09-30 按需求取消重抽）
                        wins = [sym] * min(1, int(stock[sym]["remaining"]))
                        result = "prize"
                        break
                    # triple
                    if sym == DIAMOND:
                        if not jackpot_enabled:
                            continue
                        # 超级大奖：除大奖外每类有库存的奖品各 ×1（与权重无关）
                        wins = [
                            pid
                            for pid, row in stock.items()
                            if not row["is_grand"] and row["remaining"] > 0
                        ]
                        if wins:
                            result = "prize"
                        break
                    if stock[sym]["is_grand"]:
                        other = [
                            pid
                            for pid, row in stock.items()
                            if not row["is_grand"]
                            and pid != DIAMOND
                            and row["remaining"] > 0
                        ]
                        wins = [sym] + ([rng.choice(other)] if other else [])
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
                    "SELECT id, name, emoji, remaining, total_stock, is_grand FROM prizes"
                    " WHERE id = ?",
                    (prize_id,),
                ).fetchone()
                if row is None or row["is_grand"] or row["remaining"] <= 0:
                    # 不消费凭据：玩家换一件仍可确认（大奖不走自选，与池规则一致）
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
        slot_diamond_weight: float | None = None,
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
                if slot_diamond_weight is not None:
                    self._conn.execute(
                        "INSERT INTO config (key, value) VALUES ('slot_diamond_weight', ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(float(slot_diamond_weight)),),
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

    # ---- 奖品 CRUD（后台可编辑奖池） ----

    def add_prize(
        self,
        pid: str,
        name: str,
        emoji: str,
        base_weight: float,
        slot_weight: float | None,
        total_stock: int,
        is_grand: bool,
    ) -> dict:
        """新增奖品（追加到展示顺序末尾，满库存起步）。

        id 重复或撞保留字（thanks/diamond）抛 ValueError。
        """
        if pid in RESERVED_PRIZE_IDS:
            raise ValueError(f"奖品 id 是保留字（thanks/diamond）: {pid}")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self._conn.execute(
                    "SELECT 1 FROM prizes WHERE id = ?", (pid,)
                ).fetchone()
                if dup:
                    raise ValueError(f"奖品 id 已存在: {pid}")
                next_sort = self._conn.execute(
                    "SELECT COALESCE(MAX(sort) + 1, 0) FROM prizes"
                ).fetchone()[0]
                slot_w = base_weight if slot_weight is None else slot_weight
                self._conn.execute(
                    "INSERT INTO prizes (id, name, emoji, sort, base_weight, slot_weight,"
                    " total_stock, remaining, is_grand) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, name, emoji, next_sort, float(base_weight), float(slot_w),
                     int(total_stock), int(total_stock), 1 if is_grand else 0),
                )
                self._conn.execute("COMMIT")
                return next(p for p in self.list_prizes() if p["id"] == pid)
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def update_prize(
        self,
        prize_id: str,
        *,
        name: str | None = None,
        emoji: str | None = None,
        is_grand: bool | None = None,
        total_stock: int | None = None,
    ) -> dict | None:
        """改名/emoji/大奖标志/总量。总量缩小时剩余库存钳制到新总量以内。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM prizes WHERE id = ?", (prize_id,)
                ).fetchone()
                if row is None:
                    self._conn.execute("COMMIT")
                    return None
                new_total = int(total_stock) if total_stock is not None else int(row["total_stock"])
                new_remaining = min(int(row["remaining"]), new_total)
                self._conn.execute(
                    "UPDATE prizes SET name = ?, emoji = ?, is_grand = ?,"
                    " total_stock = ?, remaining = ? WHERE id = ?",
                    (
                        name if name is not None else row["name"],
                        emoji if emoji is not None else row["emoji"],
                        1 if (is_grand if is_grand is not None else row["is_grand"]) else 0,
                        new_total,
                        new_remaining,
                        prize_id,
                    ),
                )
                self._conn.execute("COMMIT")
                return next(p for p in self.list_prizes() if p["id"] == prize_id)
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def delete_prize(self, prize_id: str) -> dict | None:
        """删除奖品。返回 None = 不存在；有中奖流水或已发出过抛 ValueError——
        此时删行会留下指向虚空的历史记录，引导管理员把权重/库存调 0 使其退出奖池。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT remaining, total_stock FROM prizes WHERE id = ?", (prize_id,)
                ).fetchone()
                if row is None:
                    self._conn.execute("COMMIT")
                    return None
                drawn = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM draws WHERE prize_id = ?", (prize_id,)
                ).fetchone()["n"]
                if drawn or int(row["remaining"]) < int(row["total_stock"]):
                    raise ValueError(
                        "该奖品已有中奖记录（或已发出过），删除会让历史记录失去指向；"
                        "如只需它退出奖池，把两套权重与库存都调 0 即可"
                    )
                self._conn.execute("DELETE FROM prizes WHERE id = ?", (prize_id,))
                self._conn.execute("COMMIT")
                return {"ok": True, "id": prize_id}
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def reset_history(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM draws")

    def replenish_all(self) -> None:
        with self._lock:
            self._conn.execute("UPDATE prizes SET remaining = total_stock")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
