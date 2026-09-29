"""FastAPI 入口：抽奖 API + 后台管理 API + 静态页面。"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .lottery import (
    DYNAMIC_MODES,
    effective_weights,
    probability_table,
    slot_odds,
    slot_pool,
)
from .store import DEFAULT_ADMIN_TOKEN, Store

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DB_PATH = Path(os.environ.get("LUCKY_DB", ROOT / "data" / "lucky.db"))

store = Store(DB_PATH)
rng = random.SystemRandom()

app = FastAPI(title="Lucky Play 抽奖系统", docs_url=None, redoc_url=None)

# 权重上限：防止 Infinity/NaN 落库后毒化数据库（抽奖与后台接口将持久 500）
WeightValue = Annotated[float, Field(ge=0, le=100000, allow_inf_nan=False)]

STATIC_PREFIXES = ("/css", "/js", "/assets", "/", "/admin")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """页面与静态资源每次强制 revalidate（无缓存头时浏览器启发式缓存会吞掉更新）。"""
    response = await call_next(request)
    if any(request.url.path == p or request.url.path.startswith(p + "/") for p in STATIC_PREFIXES):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 详情回显 input 时不得携带 inf/NaN，否则 Starlette 序列化直接 500。"""

    def finite(obj):
        if isinstance(obj, float):
            return obj if math.isfinite(obj) else repr(obj)
        if isinstance(obj, dict):
            return {k: finite(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [finite(v) for v in obj]
        return obj

    return JSONResponse(status_code=422, content={"detail": finite(exc.errors())})


def admin_auth(x_admin_token: str = Header(default="")) -> None:
    expected = os.environ.get("LUCKY_ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)
    if x_admin_token != expected:
        raise HTTPException(status_code=401, detail="管理令牌错误")


def _dyn() -> tuple[bool, str]:
    cfg = store.get_config()
    return cfg.get("dynamic_enabled") == "1", cfg.get("dynamic_mode", "per_win")


def _thanks_weight() -> float:
    return float(store.get_config().get("thanks_weight", "9"))


def _slot_cfg() -> dict:
    cfg = store.get_config()
    return {
        "diamond_weight": _safe_nonneg(cfg.get("slot_diamond_weight"), 10.0),
        "gamesir_enabled": cfg.get("slot_gamesir_enabled", "1") == "1",
        "jackpot_enabled": cfg.get("slot_jackpot_enabled", "1") == "1",
    }


def _safe_nonneg(raw, fallback: float) -> float:
    try:
        v = float(raw)
        return v if math.isfinite(v) and v >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _slot_pool_and_weights(dyn_enabled: bool, dyn_mode: str):
    """老虎机奖品有效权重表（独立 slot_weight 口径，与转盘权重互不影响）。"""
    prize_eff, _ = effective_weights(
        store.specs(use_slot_weight=True), _thanks_weight(), dyn_enabled, dyn_mode
    )
    return prize_eff


def slot_section(dyn_enabled: bool, dyn_mode: str) -> dict:
    """后台老虎机区块：开关、钻石权重与理论赔率（三轴独立口径）。"""
    slot = _slot_cfg()
    pool = slot_pool(
        _slot_pool_and_weights(dyn_enabled, dyn_mode),
        slot["diamond_weight"],
        slot["gamesir_enabled"],
    )
    odds = slot_odds(pool)  # 原始浮点：三同等小概率事件 round 到 4 位会被抹成 0，展示精度交给前端 pct()
    return {**slot, "odds": odds}


def _public_prizes() -> list[dict]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "emoji": p["emoji"],
            "remaining": int(p["remaining"]),
            "total": int(p["total_stock"]),
        }
        for p in store.list_prizes()
    ]


# ---- 公开接口 ----


@app.get("/api/meta")
def get_meta():
    cfg = store.get_config()
    slot = _slot_cfg()
    return {
        "event_name": cfg.get("event_name", "幸运抽奖"),
        "event_date": cfg.get("event_date", ""),
        "event_note": cfg.get("event_note", ""),
        "win_stop_at": _safe_float(cfg.get("win_stop_at"), 5.5),
        "slot": {
            "gamesir_enabled": slot["gamesir_enabled"],
            "jackpot_enabled": slot["jackpot_enabled"],
        },
    }


def _safe_float(raw, fallback: float) -> float:
    try:
        v = float(raw)
        return v if math.isfinite(v) and 0.5 <= v <= 8 else fallback
    except (TypeError, ValueError):
        return fallback


@app.get("/api/prizes")
def get_prizes():
    """剩余奖品查询接口（公开）。"""
    prizes = _public_prizes()
    return {
        "event": store.get_config().get("event_name", "幸运抽奖"),
        "prizes": prizes,
        "total_remaining": sum(p["remaining"] for p in prizes),
    }


class DrawIn(BaseModel):
    """抽奖来源：wheel=转盘（永远抽不到手柄），slot=老虎机（对对碰规则）。"""

    game: str = Field(default="wheel", pattern="^(wheel|slot)$")


@app.post("/api/draw")
def draw(payload: DrawIn | None = None):
    game = payload.game if payload else "wheel"
    dyn_enabled, dyn_mode = _dyn()
    prize_eff, thanks_eff = effective_weights(
        store.specs(), _thanks_weight(), dyn_enabled, dyn_mode
    )
    if game == "slot":
        slot = _slot_cfg()
        return store.draw_slot(
            rng,
            _slot_pool_and_weights(dyn_enabled, dyn_mode),
            slot["diamond_weight"],
            slot["gamesir_enabled"],
            slot["jackpot_enabled"],
        )
    # 转盘：盖世小鸡手柄不进转盘奖池（产品规则），其权重不参与归一化
    prize_eff.pop("gamesir", None)
    outcome = store.draw(rng, prize_eff, thanks_eff)
    outcome["game"] = "wheel"
    return outcome


@app.get("/api/sample")
def sample_results(count: int = Query(default=7, ge=1, le=20)):
    """按当前有效概率独立采样展示结果（无副作用，不扣库存）。

    供概率验证脚本与运维抽查使用：展示的是"如果抽它"的真实分布。
    """
    from .lottery import pick_result

    dyn_enabled, dyn_mode = _dyn()
    prize_eff, thanks_eff = effective_weights(
        store.specs(), _thanks_weight(), dyn_enabled, dyn_mode
    )
    prize_eff.pop("gamesir", None)  # 与转盘口径一致：手柄不进转盘奖池
    prizes = {p["id"]: p for p in store.list_prizes()}
    samples = []
    for _ in range(count):
        outcome = pick_result(rng, prize_eff, thanks_eff)
        if outcome and outcome != "thanks" and outcome in prizes:
            p = prizes[outcome]
            samples.append({"result": "prize", "id": outcome, "name": p["name"], "emoji": p["emoji"]})
        else:
            samples.append({"result": "thanks", "id": "thanks", "name": "谢谢参与", "emoji": "🙏"})
    return {"samples": samples}


class ChooseIn(BaseModel):
    """双钻自选确认：token 来自 /api/draw(slot) 的 choose 回执，一次性。"""

    token: str = Field(min_length=10, max_length=128)
    prize_id: str | None = Field(default=None, max_length=64)


@app.post("/api/slot/choose")
def slot_choose(payload: ChooseIn):
    """双钻自选确认：此刻才真正扣库存、写抽奖记录。"""
    outcome = store.choose_pending(payload.token, payload.prize_id)
    if "error" in outcome:
        # 410 = 凭据失效（无法补救，前端按谢谢参与收场）；409 = 奖品刚被抽走（可换一件）
        raise HTTPException(status_code=410 if outcome.get("expired") else 409, detail=outcome["error"])
    return outcome


# ---- 后台接口 ----


@app.get("/api/admin/state", dependencies=[Depends(admin_auth)])
def admin_state():
    dyn_enabled, dyn_mode = _dyn()
    specs = store.specs()
    tw = _thanks_weight()
    probs = probability_table(specs, tw, dyn_enabled, dyn_mode)
    # 老虎机独立权重口径：单轴真实分布 = 该奖品权重占单轴池（奖品+钻石，
    # 按开关剔手柄）份额——分母是钻石而非谢谢参与，与轴面真实概率一致
    slot_specs = store.specs(use_slot_weight=True)
    slot_eff, _ = effective_weights(slot_specs, tw, dyn_enabled, dyn_mode)
    slot_pool_map = slot_pool(slot_eff, _slot_cfg()["diamond_weight"], _slot_cfg()["gamesir_enabled"])
    slot_axis_total = sum(slot_pool_map.values())
    slot_probs = {
        pid: (slot_pool_map.get(pid, 0.0) / slot_axis_total if slot_axis_total else 0.0)
        for pid in (p["id"] for p in store.list_prizes())
    }
    # 动态转移量（权重口径）= 谢谢参与有效权重 - 基础权重，供后台解释概率来源
    _, thanks_eff = effective_weights(specs, tw, dyn_enabled, dyn_mode)
    # 后台"转盘概率"列按转盘真实口径展示：剔除手柄后重新归一化（转盘永远抽不到手柄）
    wheel_eff = {pid: w for pid, w in probs.items() if pid not in ("gamesir", "thanks")}
    wheel_total = sum(wheel_eff.values()) + probs.get("thanks", 0.0)
    if wheel_total > 0:
        probs = {**{pid: w / wheel_total for pid, w in wheel_eff.items()},
                 "gamesir": 0.0, "thanks": probs.get("thanks", 0.0) / wheel_total}
    return {
        "prizes": [
            {
                "id": p["id"],
                "name": p["name"],
                "emoji": p["emoji"],
                "base_weight": float(p["base_weight"]),
                "slot_weight": float(p["slot_weight"]),
                "total_stock": int(p["total_stock"]),
                "remaining": int(p["remaining"]),
                "probability": round(probs.get(p["id"], 0.0), 4),
                "slot_probability": round(slot_probs.get(p["id"], 0.0), 4),
            }
            for p in store.list_prizes()
        ],
        "thanks_weight": tw,
        "thanks_probability": round(probs.get("thanks", 0.0), 4),
        "thanks_bonus": round(max(0.0, thanks_eff - tw), 4),
        "dynamic_enabled": dyn_enabled,
        "dynamic_mode": dyn_mode,
        "win_stop_at": _safe_float(store.get_config().get("win_stop_at"), 5.5),
        "slot": slot_section(dyn_enabled, dyn_mode),
        "event": {
            "name": store.get_config().get("event_name", ""),
            "date": store.get_config().get("event_date", ""),
            "note": store.get_config().get("event_note", ""),
        },
        "stats": store.stats(),
    }


class WeightsIn(BaseModel):
    weights: dict[str, WeightValue] = Field(default_factory=dict)
    slot_weights: dict[str, WeightValue] = Field(default_factory=dict)
    thanks_weight: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)


@app.put("/api/admin/weights", dependencies=[Depends(admin_auth)])
def admin_weights(payload: WeightsIn):
    known = {p["id"] for p in store.list_prizes()}
    unknown = (set(payload.weights) | set(payload.slot_weights)) - known
    if unknown:
        raise HTTPException(status_code=404, detail=f"未知奖品: {sorted(unknown)}")
    store.set_weights(payload.weights, payload.thanks_weight, payload.slot_weights or None)
    return {"ok": True}


class StockIn(BaseModel):
    id: str
    remaining: int = Field(ge=0, le=100000)
    total: int | None = Field(default=None, ge=0, le=100000)


@app.put("/api/admin/stock", dependencies=[Depends(admin_auth)])
def admin_stock(payload: StockIn):
    # 剩余不得超过总量，否则 per_win 概率公式会产生超过 W 的有效权重
    prize = next((p for p in store.list_prizes() if p["id"] == payload.id), None)
    if prize is None:
        raise HTTPException(status_code=404, detail="奖品不存在")
    total = payload.total if payload.total is not None else int(prize["total_stock"])
    if payload.remaining > total:
        raise HTTPException(status_code=422, detail=f"剩余({payload.remaining})不能超过总量({total})，请同时填写总量")
    row = store.set_stock(payload.id, payload.remaining, payload.total)
    if row is None:
        raise HTTPException(status_code=404, detail="奖品不存在")
    return {"ok": True, "remaining": row["remaining"], "total": row["total_stock"]}


class DynamicIn(BaseModel):
    enabled: bool
    mode: str


@app.put("/api/admin/dynamic", dependencies=[Depends(admin_auth)])
def admin_dynamic(payload: DynamicIn):
    if payload.mode not in DYNAMIC_MODES:
        raise HTTPException(status_code=422, detail=f"mode 须为 {DYNAMIC_MODES}")
    store.set_config(
        {"dynamic_enabled": "1" if payload.enabled else "0", "dynamic_mode": payload.mode}
    )
    return {"ok": True}


class SlotIn(BaseModel):
    diamond_weight: WeightValue | None = None
    gamesir_enabled: bool | None = None
    jackpot_enabled: bool | None = None


@app.put("/api/admin/slot", dependencies=[Depends(admin_auth)])
def admin_slot(payload: SlotIn):
    """老虎机专属配置：钻石权重、手柄开关、三钻超级大奖开关。"""
    updates = {}
    if payload.diamond_weight is not None:
        updates["slot_diamond_weight"] = f"{payload.diamond_weight:g}"
    if payload.gamesir_enabled is not None:
        updates["slot_gamesir_enabled"] = "1" if payload.gamesir_enabled else "0"
    if payload.jackpot_enabled is not None:
        updates["slot_jackpot_enabled"] = "1" if payload.jackpot_enabled else "0"
    if updates:
        store.set_config(updates)
    return {"ok": True, **_slot_cfg()}


class WinStopIn(BaseModel):
    value: float = Field(ge=0.5, le=8, allow_inf_nan=False)


@app.put("/api/admin/win_stop", dependencies=[Depends(admin_auth)])
def admin_win_stop(payload: WinStopIn):
    """中奖时音乐收刀位置（秒）——由管理员试听调节，前台经 /api/meta 读取。"""
    store.set_config({"win_stop_at": f"{payload.value:.2f}"})
    return {"ok": True, "win_stop_at": payload.value}


class EventIn(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    date: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=80)


@app.put("/api/admin/event", dependencies=[Depends(admin_auth)])
def admin_event(payload: EventIn):
    updates = {}
    if payload.name is not None:
        updates["event_name"] = payload.name
    if payload.date is not None:
        updates["event_date"] = payload.date
    if payload.note is not None:
        updates["event_note"] = payload.note
    if updates:
        store.set_config(updates)
    return {"ok": True}


@app.get("/api/admin/history", dependencies=[Depends(admin_auth)])
def admin_history(limit: int = Query(default=100, ge=1, le=1000)):
    return {"records": store.history(limit)}


@app.post("/api/admin/history/reset", dependencies=[Depends(admin_auth)])
def admin_history_reset():
    store.reset_history()
    return {"ok": True}


@app.post("/api/admin/replenish", dependencies=[Depends(admin_auth)])
def admin_replenish():
    store.replenish_all()
    return {"ok": True}


# ---- 静态页面 ----

# git 不追踪空目录：新环境检出后 assets 可能不存在，挂载前兜底创建
(WEB_DIR / "assets").mkdir(parents=True, exist_ok=True)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(WEB_DIR / "admin.html")


app.mount("/css", StaticFiles(directory=WEB_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=WEB_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
