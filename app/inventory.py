"""库存与奖池的接入协议（Inventory）+ 装载工厂。

第三方接入自己的库存系统有三条路（由浅入深，详见 docs/CUSTOMIZE.md）：
1. 换奖品清单：`LUCKY_PRIZES_JSON=/path/to/prizes.json` 空库播种自定义奖品；
2. 后台增删改：`/admin` 页面或 `/api/admin/prizes` 系列接口直接编辑奖池；
3. 接自己的库存后台：实现本文件的 Inventory 协议，`LUCKY_INVENTORY=模块:类名`
   启动时动态加载，替换默认的 SQLite Store。

Inventory 协议契约（实现方必须满足）：
- 原子性：draw / draw_slot / choose_pending 在并发调用下绝不超卖——
  同一件库存只会被发出一次（SQLite 实现靠 BEGIN IMMEDIATE 事务保证）；
- 概率口径：specs() 返回参与 effective_weights 计算的奖品快照，
  use_slot_weight=True 时 base_weight 字段承载老虎机独立权重；
- 大奖语义：list_prizes() 的行含 is_grand 布尔——True 的奖品不进转盘、
  不出现在双钻自选清单、不计入三钻超级大奖；
- choose_pending 的凭据（token）由实现方自理：一次性、可过期，
  奖品被并发抽走时不消费凭据（玩家可换一件再确认）。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol

from .lottery import PrizeSpec


class Inventory(Protocol):
    """库存与奖池的统一访问面。SQLite Store 是参考实现（app/store.py）。"""

    # ---- 查询 ----
    def list_prizes(self) -> list[dict]: ...
    def get_config(self) -> dict[str, str]: ...
    def specs(self, use_slot_weight: bool = False) -> list[PrizeSpec]: ...
    def history(self, limit: int = 100) -> list[dict]: ...
    def stats(self) -> dict: ...

    # ---- 抽奖（契约：原子扣减、绝不超卖） ----
    def draw(self, rng, prize_eff: dict[str, float], thanks_eff: float) -> dict: ...
    def draw_slot(
        self,
        rng,
        prize_eff: dict[str, float],
        diamond_weight: float,
        grand_enabled: bool,
        jackpot_enabled: bool,
    ) -> dict: ...
    def choose_pending(self, token: str, prize_id: str | None) -> dict: ...

    # ---- 配置与库存管理 ----
    def set_config(self, updates: dict[str, str]) -> None: ...
    def set_weights(
        self,
        weights: dict[str, float],
        thanks_weight: float | None,
        slot_weights: dict[str, float] | None = None,
        slot_diamond_weight: float | None = None,
    ) -> None: ...
    def set_stock(self, prize_id: str, remaining: int, total: int | None = None) -> dict | None: ...
    def replenish_all(self) -> None: ...

    # ---- 奖品 CRUD ----
    def add_prize(
        self,
        pid: str,
        name: str,
        emoji: str,
        base_weight: float,
        slot_weight: float | None,
        total_stock: int,
        is_grand: bool,
    ) -> dict: ...
    def update_prize(
        self,
        prize_id: str,
        *,
        name: str | None = None,
        emoji: str | None = None,
        is_grand: bool | None = None,
        total_stock: int | None = None,
    ) -> dict | None: ...
    def delete_prize(self, prize_id: str) -> dict | None: ...

    # ---- 流水与生命周期 ----
    def reset_history(self) -> None: ...
    def close(self) -> None: ...


def load_inventory(
    db_path: Path,
    prizes_file: Path | str | None = None,
    spec: str = "",
) -> Inventory:
    """按 LUCKY_INVENTORY 装载库存实现，缺省 SQLite Store。

    spec 形如 "my_package.my_module:MyInventory"（模块路径:类名）。
    第三方实现的构造签名约定为 (db_path: Path)；库存不在本地文件时自行忽略
    该参数（SQLite Store 额外接受可选的 prizes_file 用于自定义播种）。
    """
    if not spec:
        from .store import Store

        return Store(db_path, prizes_file=prizes_file)
    mod_name, _, cls_name = spec.partition(":")
    if not mod_name or not cls_name:
        raise RuntimeError(
            f"LUCKY_INVENTORY 格式应为 '模块路径:类名'，当前值: {spec!r}"
        )
    try:
        module = importlib.import_module(mod_name)
        cls = getattr(module, cls_name)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"装载 LUCKY_INVENTORY={spec!r} 失败: {exc}") from exc
    return cls(db_path)
