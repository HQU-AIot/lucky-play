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

    def test_off_mode_literal_disables_transfer(self):
        """mode="off" 与关动态转移等价（docstring 承诺）：抽空奖品权重不放给谢谢参与。

        外部 Inventory 实现可能回传 (enabled=True, mode="off")，行为必须在
        effective_weights 入口统一归一，不能依赖调用方自觉。"""
        eff, thanks = effective_weights(make_specs(), 9, True, DYNAMIC_OFF)
        assert eff["b"] == 20.0  # 未按 per_win 缩放
        assert eff["c"] == 0.0
        assert thanks == 9.0  # 已抽空的 c（权重 50）不转移进来


class TestContractViolation:
    def test_remaining_over_total_clamped(self):
        """remaining > total 属 Inventory 契约违约输入：钳制到满库存口径，
        有效权重不超过 W、谢谢参与有效权重不为负（负值会让"谢谢"永不出现）。"""
        specs = [PrizeSpec("x", "违约奖", 10, 5, 8)]  # remaining 8 > total 5
        eff, thanks = effective_weights(specs, 3, True, DYNAMIC_PER_WIN)
        assert eff["x"] == 10.0  # 钳到 W，而不是 10*8/5=16
        assert thanks == 3.0  # 无负 bonus


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