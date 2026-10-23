"""接入外部库存后台的示例骨架（非运行依赖，仅供参考）。

用法：把本文件拷到自己的包里改造，然后

    LUCKY_INVENTORY=my_pkg.remote_inventory:RemoteInventory uv run uvicorn app.main:app

约定（完整契约见 app/inventory.py 的 Inventory 协议 docstring）：
- 构造签名 ``__init__(self, db_path: Path)``（库存全在远端时可忽略该参数）；
- draw / draw_slot / choose_pending 必须保证并发下绝不超卖——同一件库存只发一次；
- list_prizes() 的行带 is_grand 布尔，True 的奖品走"终极大奖"规则。

最省力的两条路：
1. 抽奖编排仍用本项目的 SQLite Store（重抽循环、双钻凭据、流水审计都是现成的），
   只在活动前后同步远端库存——见下方 SyncingInventory；
2. 彻底自管：完整实现 Inventory 协议，抽奖事务逻辑参考 app/store.py。

依赖 httpx 时自行安装（uv add httpx 或 uv pip install httpx）。
"""

from __future__ import annotations

from pathlib import Path

from app.store import Store


class SyncingInventory(Store):
    """远端库存镜像：本地 SQLite 仍是抽奖事实源，每次变动同步推给远端后台。

    适合"奖品发放要在自己的系统里留账"的场景：抽奖性能与离线能力不变，
    远端宕机只影响同步（记日志重试），不影响现场抽奖。
    """

    SYNC_URL = "https://your-inventory-api.example.com/lucky/sync"
    API_KEY = "CHANGE_ME"

    def _push(self, event: dict) -> None:
        # 这里接你自己的后台：httpx.post(self.SYNC_URL, json=event, headers=...)
        # 失败策略自行决定：重试队列 / 本地 outbox / 仅告警。不要在这里抛出
        # 异常打断抽奖主流程，除非业务要求"远端记账成功才算发奖"。
        print(f"[sync] {event}")  # pragma: no cover - 示例占位

    def draw(self, rng, prize_eff, thanks_eff):  # noqa: D102
        out = super().draw(rng, prize_eff, thanks_eff)
        if out.get("prize"):
            self._push({"kind": "grant", "prize_id": out["prize"]["id"], "qty": 1})
        return out

    def draw_slot(self, rng, prize_eff, diamond_weight, grand_enabled, jackpot_enabled):  # noqa: D102
        out = super().draw_slot(
            rng, prize_eff, diamond_weight, grand_enabled, jackpot_enabled
        )
        for p in out.get("prizes") or []:
            self._push({"kind": "grant", "prize_id": p["id"], "qty": 1})
        return out

    def choose_pending(self, token, prize_id):  # noqa: D102
        out = super().choose_pending(token, prize_id)
        if out.get("result") == "prize" and out.get("prize"):
            self._push({"kind": "grant", "prize_id": out["prize"]["id"], "qty": 1})
        return out

    def replenish_all(self) -> None:  # noqa: D102
        super().replenish_all()
        self._push({"kind": "replenish_all"})


if __name__ == "__main__":
    # 本地试跑：python examples/remote_inventory.py
    inv = SyncingInventory(Path("/tmp/lucky-example.db"))
    print(inv.list_prizes())
