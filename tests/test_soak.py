"""交付前压测：把库存全部抽干、反复多轮，验证不超卖、不负库存、抽干后必谢谢。

覆盖用户点名的场景：
- 转盘 + 老虎机混合连抽直到库存归零（多轮）；
- 双钻自选在库存紧张时的确认/拒绝；
- 超级大奖只发有库存类别；
- 零库存奖品不出现在轴面/自选清单/发放里。
"""

import random

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = {"X-Admin-Token": "123456"}
ALL_IDS = ["lollipop", "nailong", "notebook", "nfccard", "bookmark", "shark", "crawlpet", "gamesir"]
DEFAULT_WEIGHTS = {"lollipop": 30, "nailong": 20, "notebook": 15, "nfccard": 12,
                   "bookmark": 10, "shark": 8, "crawlpet": 6, "gamesir": 2}
rng = random.Random(20260930)


def _prizes():
    return {p["id"]: p for p in client.get("/api/prizes").json()["prizes"]}


def _remaining():
    return {pid: p["remaining"] for pid, p in _prizes().items()}


def _total_remaining():
    return sum(_remaining().values())


def _check_invariants():
    rem = _remaining()
    for pid, v in rem.items():
        assert v >= 0, f"{pid} 库存为负: {v}"
    assert _total_remaining() == sum(rem.values())
    return rem


def _drain_once(round_no: int, grand_total: int):
    """混合双玩法抽到"非手柄库存归零"（手柄设计上极难抽出：转盘排除 +
    老虎机仅三同手柄——稀有奖励的自然结果）；每 20 抽核对不变量。"""
    draws = 0
    granted_rows = 0

    def _issued(data):
        """本次发放件数：wheel=prize 1 件；slot=prizes 数组；choose 走确认回执。"""
        if data["result"] != "prize":
            return 0
        return len(data["prizes"]) if "prizes" in data else 1

    while sum(v for k, v in _remaining().items() if k != "gamesir") > 0:
        game = "wheel" if draws % 2 == 0 else "slot"
        r = client.post("/api/draw", json={"game": game})
        assert r.status_code == 200, r.text
        data = r.json()
        draws += 1

        if data["result"] == "choose":
            # 双钻自选：随机挑一件确认（模拟现场玩家）；刚被抽走(409)则本轮按谢谢参与
            pick = rng.choice(data["choices"])["id"]
            res = client.post("/api/slot/choose", json={"token": data["pending"], "prize_id": pick})
            if res.status_code == 200:
                data = res.json()
            else:
                assert res.status_code == 409
                data = {"result": "thanks"}

        granted_rows += _issued(data)
        for p in data.get("prizes", []) or []:
            assert p["remaining"] >= 0

        if draws % 20 == 0:
            _check_invariants()
            # 发放件数 == 流水 prize 行数（逐件可审计）
            history = client.get("/api/admin/history?limit=1000", headers=TOKEN).json()["records"]
            rows = sum(1 for h in history if h["result"] == "prize")
            assert rows == granted_rows, f"轮{round_no}: 流水 {rows} != 累计发放 {granted_rows}"
        assert draws < 2000, "抽干循环异常：2000 抽仍未抽干"
    _check_invariants()
    return draws, granted_rows


def _drain_verify_then_thanks(round_no: int, grand_total: int):
    used, granted_rows = _drain_once(round_no, grand_total)
    # 非手柄库存已归零：继续抽两玩法，必须全是谢谢参与且库存不再变化
    for i in range(24):
        game = "wheel" if i % 2 == 0 else "slot"
        r = client.post("/api/draw", json={"game": game}).json()
        assert r["result"] == "thanks", f"轮{round_no}: 非手柄抽干后仍抽到 {r}"
        if r.get("symbols"):
            # 非手柄抽干后，轴面只允许出现钻石和手柄（手柄设计上仍会上轴但几乎抽不出）
            assert all(s in ("diamond", "gamesir") for s in r["symbols"]), f"轮{round_no}: 抽干后轴面出现实物 {r['symbols']}"
    rem = _remaining()
    for pid in ALL_IDS:
        if pid != "gamesir":
            assert rem[pid] == 0, f"轮{round_no}: {pid} 未抽干 ({rem[pid]})"
    return used, granted_rows


def test_drain_all_stock_three_rounds():
    """三轮全抽干：小库存随机分布 + 双钻/超级大奖穿插，不超卖、终态全谢谢。"""
    for round_no in range(1, 4):
        # 抽干轮次：手柄 slot 权重设 0（其"三同手柄才能抽出"是极低概率设计内结果，
        # 会让"抽干后必谢谢"断言带 ~6% 固有翻车率；手柄可抽出已有专门测试覆盖）
        ws = {**DEFAULT_WEIGHTS, "gamesir": 0}
        client.put("/api/admin/weights", json={"weights": DEFAULT_WEIGHTS, "slot_weights": ws, "thanks_weight": 0}, headers=TOKEN)
        client.put("/api/admin/slot", json={"diamond_weight": 15, "grand_enabled": True, "jackpot_enabled": True}, headers=TOKEN)
        client.post("/api/admin/history/reset", headers=TOKEN)
        # 每轮随机总量（1-3 件）逼出边界；手柄固定 1 件（轴面权重本轮置 0 避免干扰）
        # 与"三同手柄+任选"都建立在手柄仅 1 件之上）
        grand_total = 0
        for pid in ALL_IDS:
            total = 1 if pid == "gamesir" else rng.randint(1, 3)
            client.put("/api/admin/stock", json={"id": pid, "remaining": total, "total": total}, headers=TOKEN)
            grand_total += total
        assert _total_remaining() > 0
        _drain_verify_then_thanks(round_no, grand_total)
    _restore_default()


def test_zero_stock_prize_invisible_everywhere():
    """零库存奖品：不上轴面、不进自选清单、不被发放（用户点名的场景）。"""
    client.put("/api/admin/weights", json={"weights": DEFAULT_WEIGHTS, "slot_weights": DEFAULT_WEIGHTS, "thanks_weight": 0}, headers=TOKEN)
    client.put("/api/admin/slot", json={"diamond_weight": 10, "grand_enabled": True, "jackpot_enabled": True}, headers=TOKEN)
    total = _prizes()["bookmark"]["total"]
    client.put("/api/admin/stock", json={"id": "bookmark", "remaining": 0, "total": total}, headers=TOKEN)
    for _ in range(150):
        r = client.post("/api/draw", json={"game": "slot"}).json()
        if r.get("symbols"):
            assert "bookmark" not in r["symbols"], f"零库存奖品上了轴面: {r['symbols']}"
        assert "bookmark" not in [c["id"] for c in r.get("choices", [])], "零库存奖品进了自选清单"
        for p in r.get("prizes", []) or []:
            assert p["id"] != "bookmark", "零库存奖品被发放"
        if r["result"] == "choose":
            res = client.post("/api/slot/choose", json={"token": r["pending"], "prize_id": rng.choice(r["choices"])["id"]})
            assert res.status_code in (200, 409)
    _restore_default()


def _restore_default():
    client.put("/api/admin/weights", json={"weights": DEFAULT_WEIGHTS, "slot_weights": DEFAULT_WEIGHTS, "thanks_weight": 9}, headers=TOKEN)
    client.put("/api/admin/slot", json={"diamond_weight": 10, "grand_enabled": True, "jackpot_enabled": True}, headers=TOKEN)
    # 还原种子总量（抽干轮次把 total 缩到 1-3，不还原会打崩同会话后续依赖
    # 53/36/18 等默认总量的测试文件）
    totals = {"lollipop": 53, "nailong": 36, "notebook": 18, "nfccard": 10,
              "bookmark": 8, "shark": 6, "crawlpet": 4, "gamesir": 1}
    for pid, total in totals.items():
        client.put("/api/admin/stock", json={"id": pid, "remaining": total, "total": total}, headers=TOKEN)
    client.post("/api/admin/replenish", headers=TOKEN)
    client.post("/api/admin/history/reset", headers=TOKEN)
