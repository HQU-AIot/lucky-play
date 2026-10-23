# 换奖品 / 接入自己的库存系统

本项目的奖池不再是写死的：奖品、库存、权重都能换。按需求深度选一条路：

| 需求 | 方式 | 章节 |
| --- | --- | --- |
| 就想换一批奖品（活动前一次性配置） | JSON 清单播种 | §1 |
| 活动中临时加一个奖品 / 改名 / 调库存 | 后台管理页或 CRUD API | §2 |
| 奖品库存在我自己的系统里（电商/ERP/会员后台） | 实现 Inventory 协议 | §3 |

## §1 换一批奖品：`LUCKY_PRIZES_JSON`

内置的 8 件奖品只是种子（`app/store.py` 的 `DEFAULT_PRIZES`）。想整套换成自己的奖品，
写一个 JSON 清单（格式见 [`prizes.example.json`](../prizes.example.json)）：

```json
[
  {
    "id": "coupon",            // 必填：1-32 位小写字母/数字/-/_
    "name": "奶茶券",           // 必填
    "emoji": "🧋",             // 可省，默认 🎁
    "base_weight": 20,         // 必填：转盘权重（≥0）
    "slot_weight": 20,         // 可省：老虎机权重，缺省同 base_weight
    "total_stock": 5,          // 必填：总量（≥0 整数）
    "is_grand": false          // 可省：终极大奖标志，默认 false
  }
]
```

对**空库**启动时指定清单路径即可：

```bash
LUCKY_PRIZES_JSON=/path/to/prizes.json uv run uvicorn app.main:app --port 8666
```

说明：

- 播种只在**奖品表为空**时全量生效；已有库只补插清单里新增的 id，不动现场调过的权重/库存/标志。
- 想重新整套播种：换个 `LUCKY_DB` 路径（或删掉旧库文件）再启动。
- **is_grand（终极大奖）** 决定特殊规则，与奖品 id 无关：大奖不进转盘、不出现在双钻
  自选清单、不计入三钻超级大奖；"三同大奖 = 大奖 + 随机一件其它奖品"。默认种子里
  `gamesir`（盖世小鸡手柄）带此标志，你可以给任何奖品带上或摘掉它。

## §2 活动中改奖池：后台 / CRUD API

后台 `http://127.0.0.1:8666/admin`（请求头 `X-Admin-Token`，默认 `123456`，
环境变量 `LUCKY_ADMIN_TOKEN` 覆盖）：

| 操作 | 界面 | API |
| --- | --- | --- |
| 新增奖品（满库存起步，排到末尾） | 「＋ 新增奖品」表单 | `POST /api/admin/prizes` |
| 改名称 / emoji / 大奖标志 | 奖品表 ✏️ 与「大奖」复选框 | `PUT /api/admin/prizes/{id}` |
| 改总量（剩余库存自动钳制到新总量内） | 库存列总量输入 | 同上，`{"total_stock": N}` |
| 改两套权重 / 剩余库存 | 权重输入 + 库存步进器 | `PUT /api/admin/weights` / `PUT /api/admin/stock` |
| 删除奖品 | 「删除」按钮（有中奖记录会被拒） | `DELETE /api/admin/prizes/{id}` |

删除规则：**已发出过或已有中奖记录的奖品不能删**（历史记录要保留指向）。
让它退出奖池的正确姿势：两套权重与库存都调 0。

新增/修改立即生效，前台已打开的页面下一轮抽奖自动联动（前端每轮结束重拉奖池）。

## §3 接入自己的库存后台：Inventory 协议

库存不在本地、想从自己的系统（电商 / ERP / 会员后台）读写？实现
[`app/inventory.py`](../app/inventory.py) 的 `Inventory` 协议，启动时动态装载：

```bash
LUCKY_INVENTORY=my_pkg.remote_inventory:SyncingInventory uv run uvicorn app.main:app
```

协议契约（完整签名见 `app/inventory.py` docstring）：

- **原子性**：`draw / draw_slot / choose_pending` 在并发下绝不超卖——同一件库存只发一次；
- **概率口径**：`specs()` 返回奖品快照供权重计算（`use_slot_weight=True` 时承载老虎机权重）；
- **大奖语义**：`list_prizes()` 行带 `is_grand`，True 走终极大奖规则；
- **凭据**：`choose_pending` 的一次性 token 由实现方自理。

实现策略二选一：

1. **省力：继承 `Store`，只做远端同步**——抽奖事实源仍是本地 SQLite（事务/重抽/流水全复用），
   每次发放同步推送自己的后台记账。参考骨架：[`examples/remote_inventory.py`](../examples/remote_inventory.py)。
2. **彻底：完整实现协议**——库存全在你的系统里，抽奖事务逻辑照抄
   `app/store.py` 的语义（`BEGIN IMMEDIATE` → 抽取 → 逐件扣减 → 逐件落流水的等价物
   要在你的系统里做到原子）。

构造签名约定 `__init__(self, db_path: Path)`；库存全在远端时忽略该参数即可。
