"""概率模型单元测试：动态转移数学、边界、概率守恒。"""

from app.lottery import (
    DYNAMIC_DEPLETED,
    DYNAMIC_OFF,
    DYNAMIC_PER_WIN,
    PrizeSpec,
    effective_weights,
    pick_result,
    probability_table,
)


def make_specs():
    return [
        PrizeSpec("a", "奖品A", 30, 10, 10),
        PrizeSpec("b", "奖品B", 20, 5, 3),  # 已抽走 2 件
        PrizeSpec("c", "奖品C", 50, 4, 0),  # 已抽空
    ]


class TestPerWin:
    def test_linear_transfer(self):
        eff, thanks = effective_weights(make_specs(), 9, True, DYNAMIC_PER_WIN)
        assert eff["a"] == 30.0  # 未抽走，全额
        assert abs(eff["b"] - 20 * 3 / 5) < 1e-9  # 已抽走 2/5，按比例缩
        assert eff["c"] == 0.0  # 抽空
        # 转移量 = 30*0 + 20*(2/5) + 50*1 = 58
        assert abs(thanks - (9 + 58)) < 1e-9

    def test_total_mass_conserved(self):
        specs = make_specs()
        _, thanks_full = effective_weights(specs, 9, True, DYNAMIC_PER_WIN)
        for s in specs:
            s.remaining = s.total  # 全新
        eff, thanks = effective_weights(specs, 9, True, DYNAMIC_PER_WIN)
        assert sum(eff.values()) + thanks == 100 + 9
        assert sum(eff.values()) + thanks == sum(
            effective_weights(make_specs(), 9, True, DYNAMIC_PER_WIN)[0].values()
        ) + thanks_full

    def test_replenish_restores_weight(self):
        specs = make_specs()
        specs[2].remaining = specs[2].total  # 补货
        eff, thanks = effective_weights(specs, 9, True, DYNAMIC_PER_WIN)
        assert eff["c"] == 50.0
        # 概率回流后只剩 b 已抽走 2 件的转移量：9 + 20*(2/5) = 17
        assert abs(thanks - 17) < 1e-9


class TestDepleted:
    def test_only_depleted_transfers(self):
        eff, thanks = effective_weights(make_specs(), 9, True, DYNAMIC_DEPLETED)
        assert eff["a"] == 30.0
        assert eff["b"] == 20.0  # 剩余未空，保持全额
        assert eff["c"] == 0.0
        assert abs(thanks - (9 + 50)) < 1e-9

    def test_zero_total_stock_counts_as_depleted(self):
        specs = [PrizeSpec("x", "零库存奖", 10, 0, 0)]
        eff, thanks = effective_weights(specs, 5, True, DYNAMIC_DEPLETED)
        assert eff["x"] == 0.0
        assert thanks == 15.0


class TestOff:
    def test_no_transfer(self):
        eff, thanks = effective_weights(make_specs(), 9, False, DYNAMIC_PER_WIN)
        assert eff["b"] == 20.0
        assert eff["c"] == 0.0
        assert thanks == 9.0


class TestPick:
    def test_respects_zero_weight(self):
        rng = __import__("random").SystemRandom()
        eff = {"a": 0.0, "b": 10.0}
        for _ in range(200):
            assert pick_result(rng, eff, 0.0) == "b"

    def test_all_zero_falls_back_to_thanks(self):
        rng = __import__("random").SystemRandom()
        assert pick_result(rng, {"a": 0.0}, 0.0) == "thanks"

    def test_thanks_only(self):
        rng = __import__("random").SystemRandom()
        assert pick_result(rng, {"a": 0.0}, 100.0) == "thanks"

    def test_probability_table_sums_to_one(self):
        for mode in (DYNAMIC_OFF, DYNAMIC_PER_WIN, DYNAMIC_DEPLETED):
            table = probability_table(make_specs(), 9, True, mode)
            assert abs(sum(table.values()) - 1.0) < 1e-9
            assert table["thanks"] >= 9 / 109 - 1e-9
