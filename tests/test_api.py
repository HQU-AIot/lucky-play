"""API 集成测试：公开接口、后台鉴权、概率设置、并发不超卖。"""

import concurrent.futures

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = {"X-Admin-Token": "123456"}

GAMESIR = "gamesir"


def test_public_prizes_interface():
    r = client.get("/api/prizes")
    assert r.status_code == 200
    data = r.json()
    assert data["event"]
    assert len(data["prizes"]) == 8
    totals = {p["id"]: p["total"] for p in data["prizes"]}
    assert totals == {
        "lollipop": 53, "nailong": 36, "notebook": 18, "nfccard": 10, "bookmark": 8,
        "shark": 6, "crawlpet": 4, "gamesir": 1,
    }
    assert data["total_remaining"] == sum(totals.values())
    # 公开接口不暴露权重
    assert "base_weight" not in data["prizes"][0]


def test_meta():
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert r.json()["event_name"]


def test_draw_shape_and_stock_decrement():
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    r = client.post("/api/draw")
    assert r.status_code == 200
    data = r.json()
    assert data["result"] in ("prize", "thanks")
    if data["result"] == "prize":
        pid = data["prize"]["id"]
        assert data["prize"]["remaining"] == before[pid] - 1
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    delta = sum(before.values()) - sum(after.values())
    assert delta == (0 if data["result"] == "thanks" else 1)


def test_admin_requires_token():
    assert client.get("/api/admin/state").status_code == 401
    assert client.put("/api/admin/weights", json={"weights": {}}).status_code == 401


def test_admin_weights_and_probability():
    r = client.put(
        "/api/admin/weights",
        json={"weights": {"lollipop": 50}, "thanks_weight": 25},
        headers=TOKEN,
    )
    assert r.status_code == 200
    state = client.get("/api/admin/state", headers=TOKEN).json()
    lollipop = next(p for p in state["prizes"] if p["id"] == "lollipop")
    assert lollipop["base_weight"] == 50
    assert state["thanks_weight"] == 25
    probs = {p["id"]: p["probability"] for p in state["prizes"]}
    probs["thanks"] = state["thanks_probability"]
    assert abs(sum(probs.values()) - 1.0) < 1e-3

    # 动态转移关闭后，概率应精确等于权重比
    client.put("/api/admin/dynamic", json={"enabled": False, "mode": "per_win"}, headers=TOKEN)
    state = client.get("/api/admin/state", headers=TOKEN).json()
    total_w = 50 + 20 + 15 + 12 + 10 + 8 + 6 + 25  # 转盘口径：不含手柄（后台概率列已剔手柄归一化）
    lollipop = next(p for p in state["prizes"] if p["id"] == "lollipop")
    assert abs(lollipop["probability"] - 50 / total_w) < 1e-3
    client.put("/api/admin/dynamic", json={"enabled": True, "mode": "per_win"}, headers=TOKEN)
    # 还原默认权重（本测试是文件内唯一改权重不还原的用例，-k 过滤时会泄漏）
    client.put("/api/admin/weights", json={"weights": {
        "lollipop": 30, "nailong": 20, "notebook": 15, "nfccard": 12,
        "bookmark": 10, "shark": 8, "crawlpet": 6, "gamesir": 2,
    }, "thanks_weight": 9}, headers=TOKEN)


def test_admin_dynamic_mode_validation():
    r = client.put("/api/admin/dynamic", json={"enabled": True, "mode": "bogus"}, headers=TOKEN)
    assert r.status_code == 422


def test_admin_stock_update():
    r = client.put("/api/admin/stock", json={"id": "shark", "remaining": 3}, headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["remaining"] == 3
    r = client.put("/api/admin/stock", json={"id": "nope", "remaining": 1}, headers=TOKEN)
    assert r.status_code == 404
    # 还原
    client.put("/api/admin/stock", json={"id": "shark", "remaining": 6}, headers=TOKEN)


def test_admin_state_thanks_bonus_transfer():
    """后台概率解释：满库存时转移量为 0；消耗库存后转移量 > 0；库存清零时该奖品概率为 0。"""
    client.post("/api/admin/replenish", headers=TOKEN)  # 前面的测试可能已消耗库存
    state = client.get("/api/admin/state", headers=TOKEN).json()
    assert state["thanks_bonus"] == 0  # 满库存无转移
    # 谢谢参与权重临时设 0，保证抽中奖品、库存必定消耗
    client.put("/api/admin/weights", json={"weights": {}, "thanks_weight": 0}, headers=TOKEN)
    client.post("/api/draw")
    state = client.get("/api/admin/state", headers=TOKEN).json()
    assert state["thanks_bonus"] > 0
    # 库存清零的奖品概率必须为 0（所有模式下），转移量吃进它的基础权重
    client.put("/api/admin/stock", json={"id": "gamesir", "remaining": 0}, headers=TOKEN)
    state = client.get("/api/admin/state", headers=TOKEN).json()
    gamesir = next(p for p in state["prizes"] if p["id"] == "gamesir")
    assert gamesir["remaining"] == 0 and gamesir["probability"] == 0
    client.post("/api/admin/replenish", headers=TOKEN)
    client.put("/api/admin/weights", json={"weights": {}, "thanks_weight": 9}, headers=TOKEN)


def test_negative_weight_rejected():
    r = client.put(
        "/api/admin/weights", json={"weights": {"shark": -1}}, headers=TOKEN
    )
    assert r.status_code == 422


def test_non_finite_weight_rejected():
    """Infinity/NaN 一旦落库，抽奖与后台接口将持久 500，必须在入口拦截。"""
    # httpx 的 json= 参数拒绝编码 inf，须用原始报文模拟攻击请求
    raw = {"Content-Type": "application/json", **TOKEN}
    r = client.put("/api/admin/weights", content=b'{"weights": {"shark": 1e400}}', headers=raw)
    assert r.status_code == 422
    r = client.put("/api/admin/weights", content=b'{"weights": {"shark": NaN}}', headers=raw)
    assert r.status_code == 422
    r = client.put("/api/admin/weights", content=b'{"thanks_weight": 1e400}', headers=raw)
    assert r.status_code == 422
    # 确认没有毒化：抽奖仍正常
    assert client.post("/api/draw").status_code == 200


def test_stock_remaining_cannot_exceed_total():
    """剩余 > 总量会让 per_win 概率公式产生负转移，挤出谢谢参与。"""
    r = client.put(
        "/api/admin/stock", json={"id": "shark", "remaining": 60}, headers=TOKEN
    )
    assert r.status_code == 422
    r = client.put(
        "/api/admin/stock", json={"id": "shark", "remaining": 10, "total": 6}, headers=TOKEN
    )
    assert r.status_code == 422
    # 合法边界：恰好等于总量可以
    r = client.put(
        "/api/admin/stock", json={"id": "shark", "remaining": 6, "total": 6}, headers=TOKEN
    )
    assert r.status_code == 200


def test_sample_interface_no_side_effect():
    """采样接口：返回 count 条、结构正确、不扣库存。"""
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    r = client.get("/api/sample?count=7")
    assert r.status_code == 200
    samples = r.json()["samples"]
    assert len(samples) == 7
    for s in samples:
        assert s["result"] in ("prize", "thanks")
        assert s["name"] and s["emoji"]
    r2 = client.get("/api/sample?count=99")
    assert r2.status_code == 422
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after == before


def test_static_mount_directories_exist():
    """被 mount 的静态目录必须存在（git 不追踪空目录，新检出环境要能启动）。"""
    from app.main import WEB_DIR

    for sub in ("css", "js", "assets"):
        assert (WEB_DIR / sub).is_dir(), f"静态目录缺失: web/{sub}"


def test_history_and_reset():
    r = client.get("/api/admin/history?limit=5", headers=TOKEN)
    assert r.status_code == 200
    assert isinstance(r.json()["records"], list)
    assert client.post("/api/admin/history/reset", headers=TOKEN).status_code == 200
    assert client.get("/api/admin/history", headers=TOKEN).json()["records"] == []


def test_concurrent_no_oversell():
    """并发压力：唯一大奖库存 1，把它的权重拉满后 50 人经老虎机同时抢，绝不能发出 2 件。

    老虎机奖池只留手柄（其余权重 0、钻石权重 0）→ 每次转出三手柄 = 手柄 ×1。
    """
    all_ids = [p["id"] for p in client.get("/api/prizes").json()["prizes"]]
    zero = {pid: 0 for pid in all_ids if pid != GAMESIR}
    r = client.put(
        "/api/admin/weights",
        json={"weights": {**zero, GAMESIR: 100}, "slot_weights": {**zero, GAMESIR: 100}, "thanks_weight": 0},
        headers=TOKEN,
    )
    assert r.status_code == 200
    client.put("/api/admin/slot", json={"diamond_weight": 0, "grand_enabled": True}, headers=TOKEN)
    client.put("/api/admin/stock", json={"id": GAMESIR, "remaining": 1, "total": 1}, headers=TOKEN)
    client.post("/api/admin/history/reset", headers=TOKEN)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(lambda _: client.post("/api/draw", json={"game": "slot"}).json(), range(50))
        )

    wins = [r for r in results if r["result"] == "prize" and r["prize"]["id"] == GAMESIR]
    assert len(wins) == 1
    assert wins[0]["prize"]["remaining"] == 0
    assert wins[0]["symbols"] == [GAMESIR, GAMESIR, GAMESIR]
    prizes_state = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert prizes_state[GAMESIR] == 0

    # 抽空后奖池清空：再抽必然谢谢
    assert client.post("/api/draw", json={"game": "slot"}).json()["result"] == "thanks"

    # 还原默认权重、库存与老虎机配置
    default = {"lollipop": 30, "nailong": 20, "notebook": 15, "nfccard": 12,
               "bookmark": 10, "shark": 8, "crawlpet": 6, GAMESIR: 2}
    client.put("/api/admin/weights", json={"weights": default, "slot_weights": default, "thanks_weight": 9}, headers=TOKEN)
    client.put("/api/admin/stock", json={"id": GAMESIR, "remaining": 1, "total": 1}, headers=TOKEN)
    client.put("/api/admin/slot", json={"diamond_weight": 10}, headers=TOKEN)


def test_replenish_all():
    client.post("/api/draw")
    client.post("/api/admin/replenish", headers=TOKEN)
    prizes = client.get("/api/prizes").json()["prizes"]
    assert all(p["remaining"] == p["total"] for p in prizes)


def test_win_stop_at_config_and_validation():
    """中奖收刀点：默认 5.5s，后台可调，越界拒绝，非法存量回退默认。"""
    meta = client.get("/api/meta").json()
    assert meta["win_stop_at"] == 5.5
    r = client.put("/api/admin/win_stop", headers=TOKEN, json={"value": 3.2})
    assert r.status_code == 200
    assert client.get("/api/meta").json()["win_stop_at"] == 3.2
    assert client.get("/api/admin/state", headers=TOKEN).json()["win_stop_at"] == 3.2
    assert client.put("/api/admin/win_stop", headers=TOKEN, json={"value": 9}).status_code == 422
    assert client.put("/api/admin/win_stop", headers=TOKEN, json={"value": 0.2}).status_code == 422
    client.put("/api/admin/win_stop", headers=TOKEN, json={"value": 5.5})
