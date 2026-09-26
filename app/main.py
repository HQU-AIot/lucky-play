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
    return {
        "event_name": cfg.get("event_name", "幸运抽奖"),
        "event_date": cfg.get("event_date", ""),
        "event_note": cfg.get("event_note", ""),
        "win_stop_at": _safe_float(cfg.get("win_stop_at"), 4.5),
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


@app.post("/api/draw")
def draw():
    dyn_enabled, dyn_mode = _dyn()
    prize_eff, thanks_eff = effective_weights(
        store.specs(), _thanks_weight(), dyn_enabled, dyn_mode
    )
    outcome = store.draw(rng, prize_eff, thanks_eff)
    return outcome


@app.get("/api/sample")
def sample_results(count: int = Query(default=7, ge=1, le=20)):
    """按当前有效概率独立采样展示结果（无副作用，不扣库存）。

    供翻牌等形式的旁位展示：其余牌面是"如果翻它"的真实分布采样。
    """
    from .lottery import pick_result

    dyn_enabled, dyn_mode = _dyn()
    prize_eff, thanks_eff = effective_weights(
        store.specs(), _thanks_weight(), dyn_enabled, dyn_mode
    )
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


# ---- 后台接口 ----


@app.get("/api/admin/state", dependencies=[Depends(admin_auth)])
def admin_state():
    dyn_enabled, dyn_mode = _dyn()
    specs = store.specs()
    probs = probability_table(specs, _thanks_weight(), dyn_enabled, dyn_mode)
    return {
        "prizes": [
            {
                "id": p["id"],
                "name": p["name"],
                "emoji": p["emoji"],
                "base_weight": float(p["base_weight"]),
                "total_stock": int(p["total_stock"]),
                "remaining": int(p["remaining"]),
                "probability": round(probs.get(p["id"], 0.0), 4),
            }
            for p in store.list_prizes()
        ],
        "thanks_weight": _thanks_weight(),
        "thanks_probability": round(probs.get("thanks", 0.0), 4),
        "dynamic_enabled": dyn_enabled,
        "dynamic_mode": dyn_mode,
        "win_stop_at": _safe_float(store.get_config().get("win_stop_at"), 4.5),
        "event": {
            "name": store.get_config().get("event_name", ""),
            "date": store.get_config().get("event_date", ""),
            "note": store.get_config().get("event_note", ""),
        },
        "stats": store.stats(),
    }


class WeightsIn(BaseModel):
    weights: dict[str, WeightValue] = Field(default_factory=dict)
    thanks_weight: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)


@app.put("/api/admin/weights", dependencies=[Depends(admin_auth)])
def admin_weights(payload: WeightsIn):
    known = {p["id"] for p in store.list_prizes()}
    unknown = set(payload.weights) - known
    if unknown:
        raise HTTPException(status_code=404, detail=f"未知奖品: {sorted(unknown)}")
    store.set_weights(payload.weights, payload.thanks_weight)
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
