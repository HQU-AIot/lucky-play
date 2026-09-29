"""概率模型：奖品权重 + 库存 + 谢谢参与动态转移。

纯函数实现，不接触数据库，便于单元测试。

动态转移三种模式（见 docs/DESIGN.md §4）：
- off:      奖品抽完即退出奖池，概率不放给谢谢参与。
- per_win:  每抽走一件，按比例把该奖品权重让给谢谢参与；
            奖品有效权重 = W_i * R_i / S_i，抽空时恰好整体转移完。
- depleted: 整个奖品被抽空后，其全部权重一次性让给谢谢参与。
"""

from __future__ import annotations

from dataclasses import dataclass

DYNAMIC_OFF = "off"
DYNAMIC_PER_WIN = "per_win"
DYNAMIC_DEPLETED = "depleted"
DYNAMIC_MODES = (DYNAMIC_PER_WIN, DYNAMIC_DEPLETED)


@dataclass
class PrizeSpec:
    """参与概率计算所需的最小奖品快照。"""

    id: str
    name: str
    base_weight: float
    total: int
    remaining: int


def effective_weights(
    specs: list[PrizeSpec],
    thanks_weight: float,
    dynamic_enabled: bool = True,
    dynamic_mode: str = DYNAMIC_PER_WIN,
) -> tuple[dict[str, float], float]:
    """返回 (各奖品有效权重, 谢谢参与有效权重)。

    库存为 0（含从未配置库存）的奖品有效权重恒为 0，不参与抽取；
    其基础权重是否转移给谢谢参与取决于模式。
    """
    prize_eff: dict[str, float] = {}
    bonus = 0.0
    for s in specs:
        if s.total > 0 and s.remaining > 0:
            if dynamic_enabled and dynamic_mode == DYNAMIC_PER_WIN:
                prize_eff[s.id] = s.base_weight * s.remaining / s.total
                bonus += s.base_weight * (1 - s.remaining / s.total)
            else:
                prize_eff[s.id] = s.base_weight
        else:
            # 已抽空 / 零库存：无法再被抽中，权重整体让给谢谢参与。
            # per_win 的线性转移在 R=0 时恰好等于全额转移，两种模式语义连续。
            prize_eff[s.id] = 0.0
            if dynamic_enabled:
                bonus += s.base_weight
    thanks_eff = thanks_weight + bonus
    return prize_eff, thanks_eff


def pick_result(
    rng,
    prize_eff: dict[str, float],
    thanks_eff: float,
) -> str | None:
    """按有效权重做一次加权抽取。

    返回中奖奖品 id，或 "thanks" 表示谢谢参与。
    全部有效权重为 0 时兜底返回 "thanks"（理论不可达，防御用）。
    """
    names = [pid for pid, w in prize_eff.items() if w > 0]
    weights = [prize_eff[pid] for pid in names]
    total = sum(weights) + thanks_eff
    if total <= 0:
        return "thanks"
    if thanks_eff > 0:
        names.append("thanks")
        weights.append(thanks_eff)
    return rng.choices(names, weights=weights, k=1)[0]


def probability_table(
    specs: list[PrizeSpec],
    thanks_weight: float,
    dynamic_enabled: bool,
    dynamic_mode: str,
) -> dict[str, float]:
    """当前有效概率（0-1），供后台展示。总概率恒为 1。"""
    prize_eff, thanks_eff = effective_weights(specs, thanks_weight, dynamic_enabled, dynamic_mode)
    total = sum(prize_eff.values()) + thanks_eff
    if total <= 0:
        return {"thanks": 1.0}
    table = {pid: w / total for pid, w in prize_eff.items()}
    table["thanks"] = thanks_eff / total
    return table


# ---- 老虎机（三轴对对碰） ----

DIAMOND = "diamond"  # 钻石符号：代替"谢谢参与"上轴；两钻=任选非手柄奖品，三钻=超级大奖


def slot_pool(
    prize_eff: dict[str, float],
    diamond_weight: float,
    gamesir_enabled: bool,
) -> dict[str, float]:
    """老虎机单轴符号权重表：库存有效的奖品 + 钻石。

    手柄开关关闭时手柄不入池（转盘侧永远不含手柄，与此开关无关）。
    """
    pool = {
        pid: w
        for pid, w in prize_eff.items()
        if w > 0 and not (pid == "gamesir" and not gamesir_enabled)
    }
    if diamond_weight > 0:
        pool[DIAMOND] = diamond_weight
    return pool


def slot_spin(rng, pool: dict[str, float]) -> list[str]:
    """三根轴各自独立、按同一权重表抽一个符号。"""
    syms = list(pool)
    return rng.choices(syms, weights=[pool[s] for s in syms], k=3)


def slot_outcome(symbols: list[str]) -> tuple[str, str | None]:
    """三轴分类：("triple", 符号) / ("pair", 符号) / ("mixed", None)。"""
    a, b, c = symbols
    if a == b == c:
        return "triple", a
    if a == b:
        return "pair", a
    if a == c:
        return "pair", a
    if b == c:
        return "pair", b
    return "mixed", None


def slot_odds(pool: dict[str, float]) -> dict[str, float]:
    """三轴独立假设下各结果的理论概率（0-1），供后台展示。

    返回 {"triple_<sym>", "pair_<sym>", "mixed"}。注意：引擎对被禁用组合
    （手柄对/三钻当超级大奖关闭）会重抽，实际分布略偏向其余组合。
    """
    total = sum(pool.values())
    if total <= 0:
        return {"mixed": 1.0}
    p = {s: w / total for s, w in pool.items()}
    odds: dict[str, float] = {}
    triple = 0.0
    pair = 0.0
    for s, ps in p.items():
        odds[f"triple_{s}"] = ps**3
        odds[f"pair_{s}"] = 3 * ps * ps * (1 - ps)
        triple += ps**3
        pair += 3 * ps * ps * (1 - ps)
    odds["mixed"] = max(0.0, 1.0 - triple - pair)
    return odds
