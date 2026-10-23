"""奖品 CRUD、is_grand 标志语义、自定义播种与外部库存装载测试。"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TOKEN = {"X-Admin-Token": "123456"}


def _prizes():
    return {p["id"]: p for p in client.get("/api/prizes").json()["prizes"]}


def _cleanup_added(pid: str):
    """删除测试新增的奖品（未抽过、满库存，允许物理删除）。"""
    if pid in _prizes():
        client.put("/api/admin/stock", json={"id": pid, "remaining": 1, "total": 1}, headers=TOKEN)
        r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
        assert r.status_code == 200, r.text


# ---- CRUD ----

def test_add_update_delete_prize_roundtrip():
    pid = "crud_test"
    _cleanup_added(pid)
    r = client.post("/api/admin/prizes", headers=TOKEN, json={
        "id": pid, "name": "测试奖品", "emoji": "🧪",
        "base_weight": 5, "total_stock": 3,
    })
    assert r.status_code == 200, r.text
    p = r.json()["prize"]
    assert p["remaining"] == 3 and p["is_grand"] is False
    # slot_weight 缺省 = base_weight
    assert p["slot_weight"] == 5
    # 公开接口可见
    assert pid in _prizes()

    # 改名 / emoji / 大奖标志
    r = client.put(f"/api/admin/prizes/{pid}", headers=TOKEN,
                   json={"name": "改名奖品", "emoji": "🎯", "is_grand": True})
    assert r.status_code == 200
    p = _prizes()[pid]
    assert p["name"] == "改名奖品" and p["is_grand"] is True

    # 未抽出过 → 允许物理删除
    r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
    assert r.status_code == 200
    assert pid not in _prizes()


def test_add_duplicate_id_rejected():
    r = client.post("/api/admin/prizes", headers=TOKEN, json={
        "id": "lollipop", "name": "撞id", "base_weight": 1, "total_stock": 1,
    })
    assert r.status_code == 409


def test_add_invalid_id_rejected():
    for bad in ("UPPER", "带中文", "x" * 33, ""):
        r = client.post("/api/admin/prizes", headers=TOKEN, json={
            "id": bad, "name": "非法id", "base_weight": 1, "total_stock": 1,
        })
        assert r.status_code == 422, bad


def test_delete_protected_when_issued_or_drawn():
    """已发出过或已有中奖流水：409 拒删（保护历史记录指向）。"""
    pid = "del_guard"
    _cleanup_added(pid)
    try:
        client.post("/api/admin/prizes", headers=TOKEN, json={
            "id": pid, "name": "删除保护", "emoji": "🛡️",
            "base_weight": 100, "total_stock": 2, "is_grand": True,
        })
        # 其它奖品权重清零，保证抽中它（大奖走老虎机：三同大奖 = 大奖 + 随机一件其它）
        weights = {k: 0 for k in _prizes()}
        client.put("/api/admin/weights", headers=TOKEN,
                   json={"weights": weights, "slot_weights": {**weights, pid: 100}, "thanks_weight": 0})
        client.put("/api/admin/slot", headers=TOKEN, json={"diamond_weight": 0})
        got = None
        for _ in range(60):
            r = client.post("/api/draw", json={"game": "slot"}).json()
            if r["result"] == "prize":
                got = r
                break
        assert got and any(p["id"] == pid for p in got["prizes"])
        # 已发出 → 拒删
        r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
        assert r.status_code == 409
        assert "权重" in r.json()["detail"]  # 引导调零退出奖池
        # 清空流水后仍拒（remaining < total）
        client.post("/api/admin/history/reset", headers=TOKEN)
        r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
        assert r.status_code == 409
        # 补回满库存 + 无流水 → 允许删除
        client.put("/api/admin/stock", json={"id": pid, "remaining": 2, "total": 2}, headers=TOKEN)
        r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
        assert r.status_code == 200
    finally:
        _restore_defaults()


def test_update_total_clamps_remaining():
    pid = "clamp_test"
    _cleanup_added(pid)
    client.post("/api/admin/prizes", headers=TOKEN, json={
        "id": pid, "name": "缩量", "base_weight": 1, "total_stock": 10,
    })
    r = client.put(f"/api/admin/prizes/{pid}", headers=TOKEN, json={"total_stock": 4})
    assert r.status_code == 200
    p = _prizes()[pid]
    assert p["total"] == 4 and p["remaining"] == 4  # 满库存被钳到新总量
    client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)


# ---- is_grand 语义（换奖品后规则随标志走，不认写死的 id） ----

def test_grand_flag_drives_wheel_exclusion():
    """把"大奖"标志从手柄挪到普通奖品：转盘立刻抽不到新大奖、抽得回手柄。"""
    # bookmark 标成大奖、gamesir 摘掉大奖
    client.put("/api/admin/prizes/bookmark", headers=TOKEN, json={"is_grand": True})
    client.put("/api/admin/prizes/gamesir", headers=TOKEN, json={"is_grand": False})
    client.put("/api/admin/stock", json={"id": "gamesir", "remaining": 1, "total": 1}, headers=TOKEN)
    try:
        # 后台转盘概率列先验证：大奖=0、原大奖（已摘标志）恢复为正
        ws = {k: 0 for k in _prizes()}
        client.put("/api/admin/weights", headers=TOKEN,
                   json={"weights": {**ws, "bookmark": 100, "gamesir": 100}, "thanks_weight": 0})
        state = client.get("/api/admin/state", headers=TOKEN).json()
        assert next(p for p in state["prizes"] if p["id"] == "bookmark")["probability"] == 0.0
        assert next(p for p in state["prizes"] if p["id"] == "gamesir")["probability"] > 0
        # 转盘行为验证：只有 bookmark（大奖）与 gamesir（已摘大奖）有权重、谢谢 0
        # → 转盘只会发 gamesir，永远发不出 bookmark
        seen = set()
        for _ in range(40):
            r = client.post("/api/draw", json={"game": "wheel"}).json()
            if r["result"] == "prize":
                seen.add(r["prize"]["id"])
        assert "bookmark" not in seen
        assert "gamesir" in seen  # 摘掉大奖标志后，转盘恢复可抽
    finally:
        client.put("/api/admin/prizes/bookmark", headers=TOKEN, json={"is_grand": False})
        client.put("/api/admin/prizes/gamesir", headers=TOKEN, json={"is_grand": True})
        _restore_defaults()


def test_migrated_grand_flag_and_config_key():
    """老库升级：gamesir 被一次性补标 is_grand，旧配置键迁移到新键。"""
    state = client.get("/api/admin/state", headers=TOKEN).json()
    grand_ids = {p["id"] for p in state["prizes"] if p["is_grand"]}
    assert "gamesir" in grand_ids
    # 旧键不再出现，新键可读写
    r = client.put("/api/admin/slot", headers=TOKEN, json={"grand_enabled": False})
    assert r.status_code == 200 and r.json()["grand_enabled"] is False
    meta = client.get("/api/meta").json()
    assert meta["slot"]["grand_enabled"] is False
    client.put("/api/admin/slot", headers=TOKEN, json={"grand_enabled": True})


def test_v2_database_upgrades_in_place(tmp_path):
    """真·老库升级：手工构造 v2 结构（无 is_grand 列 + 旧配置键 slot_gamesir_enabled），
    Store 打开时迁移分支必须真实执行——补标大奖、改配置键、不动现场数据。"""
    import sqlite3

    from app.store import Store

    db = tmp_path / "v2.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE prizes (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '🎁',
            sort INTEGER NOT NULL DEFAULT 0, base_weight REAL NOT NULL DEFAULT 0,
            total_stock INTEGER NOT NULL DEFAULT 0, remaining INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            result TEXT NOT NULL, prize_id TEXT, prize_name TEXT
        );
        INSERT INTO prizes VALUES
            ('lollipop', '不二家棒棒糖', '🍭', 0, 30, 53, 17),
            ('gamesir', '盖世小鸡手柄', '🎮', 1, 2, 1, 1);
        INSERT INTO config VALUES ('slot_gamesir_enabled', '0'), ('thanks_weight', '9');
        """
    )
    conn.commit()
    conn.close()

    store = Store(db)
    rows = {p["id"]: p for p in store.list_prizes()}
    assert rows["gamesir"]["is_grand"] == 1  # v2 → v3 一次性补标
    assert rows["lollipop"]["is_grand"] == 0
    assert rows["lollipop"]["remaining"] == 17  # 现场数据原样保留
    cfg = store.get_config()
    assert "slot_gamesir_enabled" not in cfg  # 旧键已迁移删除
    assert cfg["slot_grand_enabled"] == "0"  # 值原样带走（现场关着的还是关着）
    store.close()


# ---- LUCKY_PRIZES_JSON 自定义播种 ----

def test_custom_seed_json(tmp_path):
    """独立子进程按 JSON 清单播种新库（含自定义大奖），并验证环境变量接线。"""
    seed = tmp_path / "prizes.json"
    seed.write_text(json.dumps([
        {"id": "coupon", "name": "奶茶券", "emoji": "🧋", "base_weight": 20, "total_stock": 5},
        {"id": "console", "name": " Switch", "emoji": "🎮", "base_weight": 2,
         "slot_weight": 6, "total_stock": 1, "is_grand": True},
    ], ensure_ascii=False), encoding="utf-8")
    db = tmp_path / "seed.db"
    # 走 app.main 的环境变量接线（LUCKY_PRIZES_JSON → Store 播种），而非直接调 Store
    code = (
        "import os\n"
        "os.environ['LUCKY_PRIZES_JSON'] = {seed!r}\n"
        "os.environ['LUCKY_DB'] = {db!r}\n"
        "import urllib.request, json\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app)\n"
        "ids = {{p['id']: p for p in c.get('/api/prizes').json()['prizes']}}\n"
        "assert set(ids) == {{'coupon', 'console'}}, ids\n"
        "assert ids['console']['is_grand'] is True\n"
        "print('SEED_OK')\n"
    ).format(seed=str(seed), db=str(db))
    env = {**os.environ, "LUCKY_PRIZES_JSON": str(seed), "LUCKY_DB": str(db)}
    env.pop("LUCKY_INVENTORY", None)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent, env=env)
    assert "SEED_OK" in out.stdout, out.stderr


def test_bad_seed_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"id": "x", "name": ""}]), encoding="utf-8")
    code = (
        "from pathlib import Path\n"
        "from app.store import Store\n"
        f"Store(Path({str(tmp_path / 'bad.db')!r}), prizes_file={str(bad)!r})\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode != 0 and "name 非法" in out.stderr


def test_seed_json_validation_guards(tmp_path):
    """播种入口的防御：Infinity 毒化、重复 id、保留字 id 都要在装载期给出
    带位置信息的 ValueError，而不是 inf 落库或裸抛 sqlite3.IntegrityError。"""
    from app.store import load_seed

    inf_file = tmp_path / "inf.json"
    inf_file.write_text('[{"id": "a", "name": "A", "base_weight": Infinity, "total_stock": 1}]',
                        encoding="utf-8")
    try:
        load_seed(inf_file)
        raise AssertionError("Infinity 权重应被拒绝")
    except ValueError as exc:
        assert "有限" in str(exc)

    dup_file = tmp_path / "dup.json"
    dup_file.write_text(json.dumps([
        {"id": "a", "name": "A", "base_weight": 1, "total_stock": 1},
        {"id": "a", "name": "A2", "base_weight": 1, "total_stock": 1},
    ]), encoding="utf-8")
    try:
        load_seed(dup_file)
        raise AssertionError("重复 id 应被拒绝")
    except ValueError as exc:
        assert "重复" in str(exc)

    for rid in ("thanks", "diamond"):
        res_file = tmp_path / f"{rid}.json"
        res_file.write_text(json.dumps([
            {"id": rid, "name": "撞保留字", "base_weight": 1, "total_stock": 1},
        ]), encoding="utf-8")
        try:
            load_seed(res_file)
            raise AssertionError(f"保留字 id {rid} 应被拒绝")
        except ValueError as exc:
            assert "保留字" in str(exc)


def test_blank_name_rejected():
    """纯空白名称：新增与编辑两条路径都要 422（strip 后非空）。"""
    r = client.post("/api/admin/prizes", headers=TOKEN, json={
        "id": "blank_test", "name": "   ", "base_weight": 1, "total_stock": 1,
    })
    assert r.status_code == 422
    r = client.put("/api/admin/prizes/lollipop", headers=TOKEN, json={"name": "  "})
    assert r.status_code == 422


def test_reserved_prize_id_rejected():
    """保留字 id（thanks/diamond）：CRUD 新增路径也要拒绝（409 + 明确原因）。"""
    for rid in ("thanks", "diamond"):
        r = client.post("/api/admin/prizes", headers=TOKEN, json={
            "id": rid, "name": "撞保留字", "base_weight": 1, "total_stock": 1,
        })
        assert r.status_code == 409, (rid, r.status_code)
        assert "保留字" in r.json()["detail"]


# ---- LUCKY_INVENTORY 外部实现装载 ----

def test_load_inventory_custom_spec(tmp_path):
    """工厂按 '模块:类名' 装载第三方实现；缺协议方法的实现启动即报错；
    缺省返回 Store。"""
    from app.inventory import load_inventory
    from app.store import Store

    assert isinstance(load_inventory(tmp_path / "x.db"), Store)

    stub = tmp_path / "stub_inv.py"
    stub.write_text(
        "from app.store import Store\n"
        "class MyStore(Store):\n"
        "    '''完整协议实现（继承参考实现）——应装载成功。'''\n",
        encoding="utf-8",
    )
    broken = tmp_path / "broken_inv.py"
    broken.write_text(
        "class Broken:\n"
        "    def __init__(self, db_path):\n"
        "        self.db_path = db_path\n"
        "    def ping(self):\n"
        "        return 'stub'\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        inv = load_inventory(tmp_path / "y.db", spec="stub_inv:MyStore")
        assert isinstance(inv, Store)
        # 缺协议方法：启动期 fail-fast（而不是活动中首次调用才 AttributeError）
        try:
            load_inventory(tmp_path / "z.db", spec="broken_inv:Broken")
            raise AssertionError("缺方法的实现应当装载失败")
        except RuntimeError as exc:
            assert "缺少" in str(exc) and "draw_slot" in str(exc)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("stub_inv", None)
        sys.modules.pop("broken_inv", None)

    # 坏格式 / 坏模块：清晰报错
    for spec in ("no_colon", "nope_mod:Nope", "stub_inv:Missing"):
        try:
            load_inventory(tmp_path / "z2.db", spec=spec)
            raise AssertionError(f"{spec} 应当失败")
        except RuntimeError as exc:
            assert "LUCKY_INVENTORY" in str(exc) or "装载" in str(exc)


def _restore_defaults():
    """还原默认权重/库存/开关（供本文件各测试收尾）。"""
    defaults = {"lollipop": 30, "nailong": 20, "notebook": 15, "nfccard": 12,
                "bookmark": 10, "shark": 8, "crawlpet": 6, "gamesir": 2}
    extra = [pid for pid in _prizes() if pid not in defaults]
    for pid in extra:  # 测试残留的自定义奖品清掉
        client.put("/api/admin/stock", json={"id": pid, "remaining": 0, "total": 0}, headers=TOKEN)
        r = client.delete(f"/api/admin/prizes/{pid}", headers=TOKEN)
        if r.status_code == 409:
            client.put(f"/api/admin/prizes/{pid}", headers=TOKEN, json={"is_grand": False})
    client.put("/api/admin/weights", headers=TOKEN,
               json={"weights": defaults, "slot_weights": defaults, "thanks_weight": 9})
    client.put("/api/admin/slot", headers=TOKEN,
               json={"diamond_weight": 10, "grand_enabled": True, "jackpot_enabled": True})
    client.post("/api/admin/replenish", headers=TOKEN)
