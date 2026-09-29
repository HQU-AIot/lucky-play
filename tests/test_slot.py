"""老虎机对对碰规则、多奖品库存事务与概率灵敏度测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = {"X-Admin-Token": "123456"}
DIAMOND = "diamond"
GAMESIR = "gamesir"

ALL_IDS = ["lollipop", "nailong", "notebook", "nfccard", "bookmark", "shark", "crawlpet", GAMESIR]
DEFAULT_WEIGHTS = {"lollipop": 30, "nailong": 20, "notebook": 15, "nfccard": 12,
                   "bookmark": 10, "shark": 8, "crawlpet": 6, GAMESIR: 2}


def _weights_only(keep: dict[str, float]) -> dict[str, float]:
    return {pid: keep.get(pid, 0) for pid in ALL_IDS}


def _rig_weights(keep: dict[str, float], thanks: float = 0):
    """测试 rig：转盘与老虎机权重一起设为 keep（老虎机轴面读独立 slot_weight）。"""
    w = _weights_only(keep)
    return client.put(
        "/api/admin/weights",
        json={"weights": w, "slot_weights": w, "thanks_weight": thanks},
        headers=TOKEN,
    )


def _slot_draw():
    r = client.post("/api/draw", json={"game": "slot"})
    assert r.status_code == 200
    return r.json()


def _restore():
    client.put("/api/admin/weights", json={"weights": DEFAULT_WEIGHTS, "slot_weights": DEFAULT_WEIGHTS, "thanks_weight": 9}, headers=TOKEN)
    client.put("/api/admin/slot", json={"diamond_weight": 10, "gamesir_enabled": True, "jackpot_enabled": True}, headers=TOKEN)
    client.post("/api/admin/replenish", headers=TOKEN)


def test_admin_slot_config_and_odds():
    """后台老虎机配置读写：钻石权重/双开关落库，赔率表齐全且归一。"""
    r = client.put("/api/admin/slot", json={"diamond_weight": 25, "gamesir_enabled": False, "jackpot_enabled": False}, headers=TOKEN)
    assert r.status_code == 200
    state = client.get("/api/admin/state", headers=TOKEN).json()
    assert state["slot"]["diamond_weight"] == 25
    assert state["slot"]["gamesir_enabled"] is False
    assert state["slot"]["jackpot_enabled"] is False
    odds = state["slot"]["odds"]
    assert abs(sum(odds.values()) - 1.0) < 1e-3
    assert "triple_gamesir" not in odds and "pair_gamesir" not in odds  # 关闭后不入池
    assert "triple_diamond" in odds and "pair_diamond" in odds
    # 公开 meta 同步开关状态（前端据此决定轴上是否放手柄）
    meta = client.get("/api/meta").json()
    assert meta["slot"]["gamesir_enabled"] is False
    assert meta["slot"]["jackpot_enabled"] is False
    _restore()
    meta = client.get("/api/meta").json()
    assert meta["slot"]["gamesir_enabled"] is True and meta["slot"]["jackpot_enabled"] is True


def test_wheel_never_grants_gamesir():
    """转盘永远抽不到盖世小鸡手柄——即便它的权重拉满。"""
    _rig_weights({GAMESIR: 100000}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    for _ in range(80):
        r = client.post("/api/draw", json={"game": "wheel"}).json()
        assert r["result"] == "thanks"  # 唯一有权重的手柄被排除 → 池空 → 谢谢
        assert r["game"] == "wheel"
    _restore()


def test_triple_normal_prize_grants_two_units():
    """三同普通奖品 = 该奖品 ×2；库存只剩 1 件时只发 1 件。"""
    _rig_weights({"lollipop": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    r = _slot_draw()
    assert r["symbols"] == ["lollipop"] * 3
    assert r["result"] == "prize"
    assert [p["id"] for p in r["prizes"]] == ["lollipop", "lollipop"]
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after["lollipop"] == 53 - 2

    # 库存只剩 1 件：三同也只发 1 件
    client.put("/api/admin/stock", json={"id": "lollipop", "remaining": 1, "total": 53}, headers=TOKEN)
    r = _slot_draw()
    assert r["result"] == "prize" and len(r["prizes"]) == 1
    _restore()


def test_triple_gamesir_grants_gamesir_plus_random_other():
    """三同手柄 = 手柄 ×1 + 恰好一件其它奖品。"""
    _rig_weights({GAMESIR: 50, "nailong": 30, "bookmark": 30}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    r = None
    for _ in range(100):
        r = _slot_draw()
        if r["symbols"] == [GAMESIR] * 3:
            break
        # 试抽会消耗其它奖品库存，快照逐抽刷新，中奖那把的"前值"才可比
        before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert r and r["symbols"] == [GAMESIR] * 3
    ids = [p["id"] for p in r["prizes"]]
    # 手柄 + 恰好一件其它有库存奖品（任选为全库存口径，不限权重）
    assert len(ids) == 2 and ids[0] == GAMESIR and ids[1] != GAMESIR
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after[GAMESIR] == before[GAMESIR] - 1  # 手柄只有 1 件
    assert after[ids[1]] == before[ids[1]] - 1
    _restore()


def test_pair_gamesir_never_wins():
    """两同手柄不构成奖项（手柄仅 1 件）：大量抽签下手柄要么不出现、要么三同整套。"""
    _rig_weights({GAMESIR: 100, "crawlpet": 1}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 3}, headers=TOKEN)
    client.put("/api/admin/stock", json={"id": "crawlpet", "remaining": 50, "total": 50}, headers=TOKEN)
    for _ in range(120):
        r = _slot_draw()
        if r["result"] == "choose":
            continue  # 双钻自选回执尚未发奖，无 prizes
        granted_gamesir = [p for p in r.get("prizes", []) if p["id"] == GAMESIR]
        if granted_gamesir:
            # 手柄只能以"三同手柄"整套出现，且单次最多 1 件
            assert r["symbols"] == [GAMESIR] * 3
            assert len(granted_gamesir) == 1
    _restore()


def test_jackpot_three_diamonds_one_of_each():
    """三同钻石 = 超级大奖：除手柄外每类有库存的奖品各 ×1（此处把爬宠清零验证"仅发有库存类别"）。"""
    _rig_weights({}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "gamesir_enabled": True, "jackpot_enabled": True}, headers=TOKEN)
    client.put("/api/admin/stock", json={"id": "crawlpet", "remaining": 0, "total": 4}, headers=TOKEN)
    r = _slot_draw()
    assert r["symbols"] == [DIAMOND] * 3
    ids = sorted(p["id"] for p in r["prizes"])
    assert ids == sorted(["lollipop", "nailong", "notebook", "nfccard", "bookmark", "shark"])
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after["crawlpet"] == 0  # 无库存的类别不发
    assert after["lollipop"] == 53 - 1 and after[GAMESIR] == 1  # 手柄不在超级大奖内
    # 每件中奖单位都有流水可审计
    history = client.get("/api/admin/history?limit=20", headers=TOKEN).json()["records"]
    prize_rows = [h for h in history if h["result"] == "prize"]
    assert len(prize_rows) == 6
    _restore()


def test_jackpot_disabled_rerolls_three_diamonds():
    """超级大奖关闭：三同钻石被重抽，只剩钻石的池子最终谢谢参与。"""
    _rig_weights({}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "jackpot_enabled": False}, headers=TOKEN)
    for _ in range(5):
        r = _slot_draw()
        assert r["result"] == "thanks"
        assert all(s == DIAMOND for s in r["symbols"])
    _restore()


def _draw_until_choose(limit: int = 100) -> dict:
    """反复抽到出现双钻自选回执为止（池里棒棒糖+钻石各半时约 28% 出现率）。"""
    for _ in range(limit):
        r = _slot_draw()
        if r["result"] == "choose":
            return r
    raise AssertionError(f"{limit} 抽内未出现双钻自选回执")


def test_pair_diamonds_offers_choice_grid_excluding_zero_stock():
    """双钻 = 弹自选清单：只含有库存的非手柄奖品（无库存绝不出现），签发一次性凭据。"""
    _rig_weights({"lollipop": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "jackpot_enabled": False}, headers=TOKEN)
    # 清空 5 件奖品库存：它们不应出现在自选清单里
    prizes_now = {p["id"]: p for p in client.get("/api/prizes").json()["prizes"]}
    for pid in ("notebook", "nfccard", "bookmark", "shark", "crawlpet"):
        client.put("/api/admin/stock", json={"id": pid, "remaining": 0, "total": prizes_now[pid]["total"]}, headers=TOKEN)
    r = _draw_until_choose()
    assert sum(1 for s in r["symbols"] if s == DIAMOND) == 2
    ids = sorted(c["id"] for c in r["choices"])
    assert ids == ["lollipop", "nailong"]  # 仅有库存者；手柄永远不在清单里
    _restore()


def test_choose_confirm_grants_and_decrements():
    """点「确认领取」那一刻才扣库存：选谁扣谁一件、落 prize 流水；凭据一次性。"""
    _rig_weights({"lollipop": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "jackpot_enabled": False}, headers=TOKEN)
    r = _draw_until_choose()
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    res = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": "lollipop"})
    assert res.status_code == 200
    data = res.json()
    assert data["result"] == "prize" and data["prize"]["id"] == "lollipop"
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after["lollipop"] == before["lollipop"] - 1
    history = client.get("/api/admin/history?limit=5", headers=TOKEN).json()["records"]
    assert history[0]["result"] == "prize" and history[0]["prize_id"] == "lollipop"
    # 凭据已消费：拿同一凭据再确认 → 拒绝（410 已失效）
    again = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": "nailong"})
    assert again.status_code == 410
    _restore()


def test_choose_rejects_out_of_stock_token_still_usable():
    """确认的奖品若刚被并发抽走：拒绝、凭据仍有效，换一件即可成功。"""
    _rig_weights({"lollipop": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "jackpot_enabled": False}, headers=TOKEN)
    r = _draw_until_choose()
    total = next(p["total"] for p in client.get("/api/prizes").json()["prizes"] if p["id"] == "lollipop")
    client.put("/api/admin/stock", json={"id": "lollipop", "remaining": 0, "total": total}, headers=TOKEN)
    res = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": "lollipop"})
    assert res.status_code == 409
    # 换清单里另一件（nailong 有库存）→ 成功
    res2 = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": "nailong"})
    assert res2.status_code == 200 and res2.json()["prize"]["id"] == "nailong"
    _restore()


def test_choose_null_grants_thanks():
    """放弃选择（prize_id=None）：落一条谢谢参与流水。"""
    _rig_weights({"lollipop": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 50, "jackpot_enabled": False}, headers=TOKEN)
    r = _draw_until_choose()
    client.post("/api/admin/history/reset", headers=TOKEN)
    res = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": None})
    assert res.status_code == 200 and res.json()["result"] == "thanks"
    history = client.get("/api/admin/history?limit=5", headers=TOKEN).json()["records"]
    assert history[0]["result"] == "thanks"
    _restore()


def test_choose_invalid_token_rejected():
    """伪造/过期凭据一律拒绝（410），且不碰库存。"""
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    res = client.post("/api/slot/choose", json={"token": "bogus-token-abcdef", "prize_id": "lollipop"})
    assert res.status_code == 410
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after == before


def test_pair_normal_prize_grants_exactly_one():
    """两同普通奖品 = 该奖品 ×1（不是 ×2）。池内两符号时高频出现对子。"""
    _rig_weights({"lollipop": 50, "nailong": 50}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    before = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    seen_pair = False
    prev = dict(before)
    for _ in range(60):
        r = _slot_draw()
        counts = {}
        for s in r["symbols"]:
            counts[s] = counts.get(s, 0) + 1
        pair_sym = next((k for k, v in counts.items() if v == 2), None)
        if pair_sym and r["result"] == "prize":
            seen_pair = True
            assert len(r["prizes"]) == 1 and r["prizes"][0]["id"] == pair_sym
            after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
            assert after[pair_sym] == prev[pair_sym] - 1  # 恰好扣 1 件
        prev = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert seen_pair
    _restore()


def test_slot_probability_follows_admin_weights():
    """后台改权重必须真实改变老虎机产出分布（管理端→前端链路端到端）。"""
    big, small = 200, 200
    client.put("/api/admin/stock", json={"id": "lollipop", "remaining": big, "total": big}, headers=TOKEN)
    client.put("/api/admin/stock", json={"id": "nailong", "remaining": small, "total": small}, headers=TOKEN)
    _rig_weights({"lollipop": 100, "nailong": 1}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)

    def granted_units(pid):
        return len([p for p in granted if p["id"] == pid])

    granted = []
    for _ in range(60):
        granted += _slot_draw()["prizes"]
    lolly_first, dragon_first = granted_units("lollipop"), granted_units("nailong")
    assert lolly_first > dragon_first * 5

    # 反转权重：分布必须跟着反转
    _rig_weights({"lollipop": 1, "nailong": 100}, 0)
    granted = []
    for _ in range(60):
        granted += _slot_draw()["prizes"]
    assert granted_units("nailong") > granted_units("lollipop") * 5
    _restore()


def test_slot_stock_never_negative():
    """并发老虎机抽奖不把任何奖品库存扣成负数。"""
    client.put("/api/admin/stock", json={"id": "crawlpet", "remaining": 3, "total": 4}, headers=TOKEN)
    _rig_weights({"crawlpet": 100}, 0)
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    with __import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: client.post("/api/draw", json={"game": "slot"}).json(), range(24)))
    after = {p["id"]: p["remaining"] for p in client.get("/api/prizes").json()["prizes"]}
    assert after["crawlpet"] >= 0
    _restore()


def test_wheel_and_slot_weights_independent():
    """两套权重独立：老虎机权重拉满棒棒糖、转盘权重拉满奶龙时互不串台。"""
    client.put(
        "/api/admin/weights",
        json={"weights": _weights_only({"nailong": 100}), "slot_weights": _weights_only({"lollipop": 100}), "thanks_weight": 0},
        headers=TOKEN,
    )
    client.put("/api/admin/slot", json={"diamond_weight": 0}, headers=TOKEN)
    # 转盘 30 抽：只可能是奶龙（棒棒糖转盘权重为 0）
    for _ in range(30):
        r = client.post("/api/draw", json={"game": "wheel"}).json()
        if r["result"] == "prize":
            assert r["prize"]["id"] == "nailong"
    # 老虎机 30 抽：三同/对子只可能是棒棒糖（奶龙 slot 权重为 0，不上轴）
    for _ in range(30):
        r = _slot_draw()
        for p in r.get("prizes", []):
            assert p["id"] == "lollipop"
        if r.get("symbols"):
            assert "nailong" not in r["symbols"]
    _restore()
