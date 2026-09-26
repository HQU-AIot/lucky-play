#!/usr/bin/env python3
"""蒙特卡洛概率核查：实测频率 vs 独立推导的理论概率。

与单元测试的区别：单元测试验证公式实现自洽；本脚本用大样本抽样验证
"配置概率 → 生效概率 → 实际抽中分布" 全链路统计收敛。

理论概率在脚本内按 docs/DESIGN.md §4 语义独立推导（不调用实现代码），
抽样则走真实代码路径（pick_result / Store.draw / HTTP API），两侧任何
不一致都会以 z 分数形式暴露。

用法：
    uv run python scripts/prob_check.py          # 全部四组核查
    uv run python scripts/prob_check.py fast     # 样本量减半，快速回归

退出码：全部通过 0，任一失败 1。
"""

from __future__ import annotations

import atexit
import math
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 独立临时库：绝不触碰 data/ 下的真实数据库（必须在 import app 之前设置）
_TMPDIR = tempfile.mkdtemp(prefix="lucky-probcheck-")
os.environ["LUCKY_DB"] = os.path.join(_TMPDIR, "lucky.db")
atexit.register(shutil.rmtree, _TMPDIR, ignore_errors=True)

from app.lottery import (  # noqa: E402
    DYNAMIC_DEPLETED,
    DYNAMIC_OFF,
    DYNAMIC_PER_WIN,
    PrizeSpec,
    effective_weights,
    pick_result,
    probability_table,
)
from app.store import DEFAULT_CONFIG, DEFAULT_PRIZES, Store  # noqa: E402

FAST = "fast" in sys.argv
SCALE = 0.5 if FAST else 1.0

Z_LIMIT = 4.0  # 单格 |z| 上限：全脚本约 70 个检验格合并误报率 <0.5%

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  ✗ {msg}")


# ---------------------------------------------------------------- 理论推导

def theory(specs: list[PrizeSpec], thanks_w: float, enabled: bool, mode: str) -> dict[str, float]:
    """按文档语义独立推导当前状态的真值概率表。

    per_win/depleted 的分母取不变量 M = ΣW + W0（而非实测权重的和），
    使"概率质量守恒"成为被检验的性质而非推导前提。
    """
    total_w = sum(s.base_weight for s in specs)
    mass = total_w + thanks_w  # per_win / depleted 模式下的不变总量
    p = {s.id: 0.0 for s in specs}
    bonus = 0.0
    available = 0.0
    for s in specs:
        can_win = s.total > 0 and s.remaining > 0
        if can_win:
            available += s.base_weight
            if enabled and mode == DYNAMIC_PER_WIN:
                p[s.id] = s.base_weight * s.remaining / s.total / mass
                bonus += s.base_weight * (1 - s.remaining / s.total)
            else:
                p[s.id] = s.base_weight / mass
        else:
            if enabled:  # off 模式抽空不让出，质量直接消失（由归一化分摊）
                bonus += s.base_weight
    if enabled:
        p["thanks"] = (thanks_w + bonus) / mass
    else:
        denom = available + thanks_w
        p["thanks"] = thanks_w / denom if denom > 0 else 1.0
        for s in specs:
            if p[s.id]:  # off 模式按可用质量归一化
                p[s.id] = s.base_weight / denom
    return p


# ---------------------------------------------------------------- 统计工具

def cell_z(obs: float, exp: float, var: float) -> float:
    if var <= 0:
        return 0.0 if abs(obs - exp) < 1e-9 else math.copysign(math.inf, obs - exp)
    return (obs - exp) / math.sqrt(var)


def report_row(name: str, obs: float, exp: float, z: float, n: float) -> bool:
    ok = abs(z) < Z_LIMIT
    mark = "·" if ok else "✗"
    print(f"    {mark} {name:<10} 理论 {exp / n:7.4%}  实测 {obs / n:7.4%}  z={z:+.2f}")
    return ok


# ---------------------------------------------------------------- 1. 冻结态抽样分布

def phase_frozen(rng: random.Random) -> None:
    print("\n[1] 冻结态抽样分布（pick_result 直接蒙特卡洛，理论值独立推导）")
    n = int(200_000 * SCALE)
    mid = [("lollipop", 13, 53), ("nailong", 9, 36), ("notebook", 4, 18),
           ("bookmark", 2, 8), ("shark", 1, 6), ("crawlpet", 1, 4), ("gamesir", 0, 1)]
    all_gone = [(pid, 0, total) for pid, _, _, _, total in DEFAULT_PRIZES]
    cases = [
        ("默认全新 · per_win", DEFAULT_PRIZES, 9.0, True, DYNAMIC_PER_WIN),
        ("中盘残局 · per_win", mid, 9.0, True, DYNAMIC_PER_WIN),
        ("中盘残局 · depleted", mid, 9.0, True, DYNAMIC_DEPLETED),
        ("中盘残局 · off", mid, 9.0, False, DYNAMIC_PER_WIN),
        ("全部抽空 · per_win", all_gone, 9.0, True, DYNAMIC_PER_WIN),
        ("谢谢权重 0 · 全新", DEFAULT_PRIZES, 0.0, True, DYNAMIC_PER_WIN),
        ("奖品权重全 0", [(pid, n_, e, 0, st) for pid, n_, e, _, st in DEFAULT_PRIZES], 9.0,
         True, DYNAMIC_PER_WIN),
    ]

    for title, rows, tw, enabled, mode in cases:
        specs = _specs_from(rows)
        eff, thanks_eff = effective_weights(specs, tw, enabled, mode)
        p = theory(specs, tw, enabled, mode)
        counts: dict[str, float] = {s.id: 0.0 for s in specs}
        counts["thanks"] = 0.0
        for _ in range(n):
            counts[pick_result(rng, eff, thanks_eff)] += 1

        print(f"  · {title}  (N={n:,})")
        worst = 0.0
        for key in sorted(counts):
            if p[key] <= 0.0:
                if counts[key] != 0:
                    fail(f"{title}: 概率 0 的 {key} 被抽中 {counts[key]:.0f} 次")
                continue
            if p[key] >= 1.0:
                if counts[key] != n:
                    fail(f"{title}: 概率 1 的 {key} 未全中（{counts[key]:.0f}/{n}）")
                continue
            var = n * p[key] * (1 - p[key])
            z = cell_z(counts[key], n * p[key], var)
            worst = max(worst, abs(z))
            if not report_row(key, counts[key], n * p[key], z, n):
                fail(f"{title}: {key} 偏离理论超限 (z={z:+.2f})")
        print(f"    最大 |z| = {worst:.2f}（上限 {Z_LIMIT}）")


def _specs_from(rows) -> list[PrizeSpec]:
    """构造 PrizeSpec 列表。rows 元素支持两种形式：
    (id, name, emoji, weight, total) —— 直接给定（remaining=total，全新）；
    (id, rem, total) —— 名称与权重从 DEFAULT_PRIZES 反查。
    """
    base = {pid: (name, float(w)) for pid, name, _, w, _ in DEFAULT_PRIZES}
    out = []
    for row in rows:
        if len(row) == 5:
            pid, name, _, w, total = row
            out.append(PrizeSpec(pid, name, float(w), total, total))
        else:
            pid, rem, total = row
            name, w = base[pid]
            out.append(PrizeSpec(pid, name, w, total, rem))
    return out


# ---------------------------------------------------------------- 2. 概率守恒扫描

def phase_conservation(rng: random.Random) -> None:
    print("\n[2] 概率守恒扫描（随机状态 × 三模式，effective_weights/probability_table）")
    bad = 0
    cases = 0
    for i in range(300):
        k = rng.randint(1, 8)
        specs = []
        for j in range(k):
            total = rng.choice([0, 1, 5, 20, 100])
            rem = rng.randint(0, total) if total else 0
            specs.append(PrizeSpec(f"p{j}", f"奖{j}", rng.uniform(0, 50), total, rem))
        tw = rng.choice([0.0, 1.0, 9.0, 55.0])
        total_w = sum(s.base_weight for s in specs)
        for enabled, mode in ((True, DYNAMIC_PER_WIN), (True, DYNAMIC_DEPLETED),
                              (False, DYNAMIC_PER_WIN), (False, DYNAMIC_DEPLETED)):
            cases += 1
            eff, thanks = effective_weights(specs, tw, enabled, mode)
            got = sum(eff.values()) + thanks
            if enabled:
                want = total_w + tw
            else:
                want = sum(s.base_weight for s in specs
                           if s.total > 0 and s.remaining > 0) + tw
            if abs(got - want) > 1e-6 * max(1.0, want):
                bad += 1
                fail(f"守恒破坏: case{i} mode={mode} enabled={enabled} got={got:.6f} want={want:.6f}")
            table = probability_table(specs, tw, enabled, mode)
            if abs(sum(table.values()) - 1.0) > 1e-9 or any(v != v for v in table.values()):
                bad += 1
                fail(f"概率表异常: case{i} mode={mode} sum={sum(table.values())}")
    print(f"  · {cases} 个随机状态组合全部过堂" if bad == 0 else f"  · {bad} 处异常")


# ---------------------------------------------------------------- 3. Store 全链路（含库存演化）

def phase_store_chain(rng: random.Random) -> None:
    print("\n[3] Store.draw 全链路蒙特卡洛（逐抽按当时状态累积理论期望，精确处理非平稳分布）")
    store = Store(Path(os.environ["LUCKY_DB"]))
    enabled = DEFAULT_CONFIG["dynamic_enabled"] == "1"
    mode = DEFAULT_CONFIG["dynamic_mode"]
    tw = float(DEFAULT_CONFIG["thanks_weight"])
    ids = [p[0] for p in DEFAULT_PRIZES]

    def run(title: str, n: int, restock: tuple[int, int] | None) -> None:
        if restock:
            for pid in ids:
                store.set_stock(pid, restock[0], restock[1])
        store.reset_history()
        obs = {pid: 0 for pid in ids}
        obs["thanks"] = 0
        exp = {pid: 0.0 for pid in ids}
        exp["thanks"] = 0.0
        var = {pid: 0.0 for pid in ids}
        var["thanks"] = 0.0
        wins = 0
        for _ in range(n):
            specs = store.specs()
            p = theory(specs, tw, enabled, mode)
            for key in exp:
                exp[key] += p[key]
                var[key] += p[key] * (1 - p[key])
            eff, thanks_eff = effective_weights(specs, tw, enabled, mode)
            out = store.draw(rng, eff, thanks_eff)
            key = out["prize"]["id"] if out["result"] == "prize" else "thanks"
            obs[key] += 1
            if out["result"] == "prize":
                wins += 1
            if all(s.remaining == 0 for s in store.specs()):
                break

        print(f"  · {title}  (实际抽 {sum(obs.values()):,} 次)")
        worst = 0.0
        for key in sorted(obs):
            z = cell_z(obs[key], exp[key], var[key])
            worst = max(worst, abs(z))
            if exp[key] >= 5 and not report_row(key, obs[key], exp[key], z, sum(obs.values())):
                fail(f"{title}: {key} 偏离累积理论期望 (z={z:+.2f})")
        print(f"    最大 |z| = {worst:.2f}")

        # 账目一致性：不超卖、库存扣减数=中奖数、流水条数=抽数
        rows = {r["id"]: r for r in store.list_prizes()}
        sold = sum(int(r["total_stock"]) - int(r["remaining"]) for r in rows.values())
        if any(int(r["remaining"]) < 0 for r in rows.values()):
            fail(f"{title}: 出现负库存")
        if sold != wins:
            fail(f"{title}: 库存扣减 {sold} ≠ 中奖次数 {wins}")
        if store.stats()["total_draws"] != sum(obs.values()):
            fail(f"{title}: 流水条数与抽数不符")

    run("默认种子库存 · 抽到全空", 200_000, None)
    run("巨量库存 200 万 · 近似平稳", int(40_000 * SCALE), (2_000_000, 2_000_000))
    store.close()


# ---------------------------------------------------------------- 4. HTTP API 层

def phase_api() -> None:
    print("\n[4] HTTP API 层（TestClient：/api/draw 扣库存链路 + /api/sample 无副作用采样）")
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    state = client.get("/api/prizes").json()
    assert all(p["total"] >= 2_000_000 for p in state["prizes"]), "API 阶段需要先跑巨量库存"

    # -- sample 无副作用 --
    before = client.get("/api/prizes").json()
    draws_before = client.get("/api/admin/history?limit=1",
                              headers={"X-Admin-Token": "123456"}).json()
    client.get("/api/sample?count=20")
    after = client.get("/api/prizes").json()
    draws_after = client.get("/api/admin/history?limit=1",
                             headers={"X-Admin-Token": "123456"}).json()
    if before != after or draws_before != draws_after:
        fail("/api/sample 产生了副作用（库存或流水变化）")
    else:
        print("  · /api/sample 无副作用：库存与流水零变化")

    # -- sample 分布（无扣减 → 状态恒定，直接平稳检验）--
    rng = random.Random(20260930)
    n_req = int(1500 * SCALE)
    counts: dict[str, int] = {}
    for _ in range(n_req):
        for s in client.get("/api/sample?count=20").json()["samples"]:
            key = s["id"] if s["result"] == "prize" else "thanks"
            counts[key] = counts.get(key, 0) + 1
    n = sum(counts.values())
    specs, tw, enabled, mode = _live_specs(client)
    p = theory(specs, tw, enabled, mode)
    print(f"  · /api/sample 分布  (N={n:,})")
    # 遍历整张理论表而非观测 key：某奖品若被实现层系统性漏发（观测恒 0）也必须报偏离
    for key in sorted(p):
        obs_n = counts.get(key, 0)
        z = cell_z(obs_n, n * p[key], n * p[key] * (1 - p[key]))
        if not report_row(key, obs_n, n * p[key], z, n):
            fail(f"/api/sample: {key} 偏离理论 (z={z:+.2f})")

    # -- draw 链路（每 1000 抽刷新一次理论期望）--
    n_draw = int(4_000 * SCALE)
    obs: dict[str, float] = {}
    exp: dict[str, float] = {}
    var: dict[str, float] = {}
    done = 0
    while done < n_draw:
        specs, tw, enabled, mode = _live_specs(client)
        p = theory(specs, tw, enabled, mode)
        if os.environ.get("PROBCHK_DEBUG"):
            print(f"    DBG batch@{done}: rem/total={[(s.id[:4], s.remaining, s.total) for s in specs]}"
                  f" tw={tw} en={enabled} mode={mode}")
            print(f"        P={ {k: round(v, 4) for k, v in p.items()} }")
        batch = min(1000, n_draw - done)
        for _ in range(batch):
            r = client.post("/api/draw").json()
            key = r["prize"]["id"] if r["result"] == "prize" else "thanks"
            obs[key] = obs.get(key, 0) + 1
        # 期望必须每抽累加整张概率表（×batch：批内状态近似不变），
        # 只累加被抽中 key 的概率会得到 期望=观测×概率 的循环推导
        for k, pk in p.items():
            exp[k] = exp.get(k, 0.0) + pk * batch
            var[k] = var.get(k, 0.0) + pk * (1 - pk) * batch
        done += batch
    total = sum(obs.values())
    print(f"  · POST /api/draw 分布  (N={total:,})")
    for key in sorted(exp):  # 同 sample 段：遍历期望表全集，漏发 key 不会静默跳过
        obs_n = obs.get(key, 0)
        z = cell_z(obs_n, exp[key], var[key])
        if not report_row(key, obs_n, exp[key], z, total):
            fail(f"/api/draw: {key} 偏离累积理论 (z={z:+.2f})")

    # -- draw 与 sample 是否同源 --
    print("  · /api/draw 与 /api/sample 均走 effective_weights → pick_result，"
          "上述两组分布各自收敛于同一理论表即互证同源")


def _live_specs(client) -> tuple[list[PrizeSpec], float, bool, str]:
    """从 admin 接口读真实配置构造状态，避免脚本内硬编码权重。"""
    st = client.get("/api/admin/state", headers={"X-Admin-Token": "123456"}).json()
    specs = [PrizeSpec(p["id"], p["name"], float(p["base_weight"]),
                       int(p["total_stock"]), int(p["remaining"])) for p in st["prizes"]]
    return specs, float(st["thanks_weight"]), bool(st["dynamic_enabled"]), str(st["dynamic_mode"])


# ---------------------------------------------------------------- main

def main() -> int:
    rng = random.Random(20260930)
    phase_frozen(rng)
    phase_conservation(rng)
    phase_store_chain(rng)
    phase_api()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果：{len(failures)} 项失败")
        return 1
    print("结果：全部通过 —— 实测频率与理论概率在统计容差内一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
