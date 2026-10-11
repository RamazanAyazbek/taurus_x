import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import short_config
from short_signal_logic import prepare_short_features, evaluate_short_hypothesis, generate_short_signal


class ShortLogicTests(unittest.TestCase):
    def make_rows(self, prices, zones=None, takers=None, highs=None, lows=None, start="2026-08-27 16:10"):
        times = pd.date_range(start, periods=len(prices), freq="10min", tz="Asia/Almaty").tz_convert("UTC")
        if zones is None:
            zones = ["NONE"] * len(prices)
        if takers is None:
            takers = [42.0] * len(prices)
        if highs is None:
            highs = list(prices)
        if lows is None:
            lows = list(prices)
        return pd.DataFrame({
            "timestamp": [t.strftime("%Y-%m-%d %H:%M") for t in times],
            "dt": times,
            "dt_local": times.tz_convert("Asia/Almaty").tz_localize(None),
            "price": prices,
            "hour_high": highs,
            "hour_low": lows,
            "dPrice": [0.0] * len(prices),
            "dOI": [0.0] * len(prices),
            "doi_xmed": [1.0] * len(prices),
            "volume": [5000.0] * len(prices),
            "vol_xmed": [1.5] * len(prices),
            "taker_buy": takers,
            "tag": ["NORMAL"] * len(prices),
            "in_zone": zones,
        })

    def test_r1_upper_half_rejection_fires(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_REJECTION")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "SHORT")
        self.assertEqual(result["short_hypothesis"], "R1_REJECTION")
        self.assertGreaterEqual(result["short_zone_position"], 0.5)

    def test_r1_lower_half_is_rejected(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79300.0],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_REJECTION")
        self.assertIsNone(result)

    def test_r1_taker_filter_blocks_dominant_buying(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 57.0],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_REJECTION")
        self.assertIsNone(result)


    def test_confirmed_r1_rejection_requires_hour_high_and_pullback(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
            # Hour high is +0.126% over the zone top: inside the allowed touch band.
            highs=[79660.0, 79520.0, 79510.0, 79600.0],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_CONFIRMED_REJECTION")
        self.assertIsNotNone(result)
        self.assertEqual(result["short_hypothesis"], "R1_CONFIRMED_REJECTION")
        self.assertGreaterEqual(
            result["short_rejection_from_high_pct"],
            short_config.SHORT_R1_CONFIRMED_MIN_PULLBACK_FROM_HIGH_PCT,
        )

    def test_confirmed_r1_rejection_requires_upper_boundary_touch(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
            highs=[79660.0, 79520.0, 79360.0, 79360.0],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_CONFIRMED_REJECTION")
        self.assertIsNone(result)

    def test_trend_continuation_uses_history_only_returns(self):
        # A steady fall over the last 4h, 2h and 10m should satisfy H1's directional filters.
        prices = [80000.0 * (1 - 0.001 * i) for i in range(31)]
        df = self.make_rows(prices)
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "TREND_CONTINUATION")
        self.assertIsNotNone(result)
        self.assertLessEqual(result["short_return_4h_pct"], short_config.SHORT_TREND_4H_MAX_RETURN_PCT)
        self.assertLessEqual(result["short_return_2h_pct"], short_config.SHORT_TREND_2H_MAX_RETURN_PCT)

    def test_confirmed_r1_rejection_rejects_high_far_above_zone(self):
        # Bug regression: a high far above R1 must not count as a touch of resistance.
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
            highs=[79660.0, 79520.0, 79510.0, 79739.1],
        )
        prepared = prepare_short_features(df, short_config)
        self.assertGreater(prepared.iloc[-1]["short_high_delta_pct"], short_config.SHORT_R1_CONFIRMED_MAX_HIGH_ABOVE_ZONE_PCT)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_CONFIRMED_REJECTION")
        self.assertIsNone(result)

    def test_confirmed_r1_rejection_rejects_late_pullback(self):
        # High barely cleared zone top, but the current price has already retreated too far.
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 78980.0],
            ["NONE", "NONE", "NONE", "R1[78.7k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
            highs=[79660.0, 79520.0, 79510.0, 79600.0],
        )
        prepared = prepare_short_features(df, short_config)
        self.assertGreater(prepared.iloc[-1]["short_rejection_from_high_pct"], short_config.SHORT_R1_CONFIRMED_MAX_PULLBACK_FROM_HIGH_PCT)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_CONFIRMED_REJECTION")
        self.assertIsNone(result)

    def test_confirmed_r1_metadata_includes_high_delta(self):
        df = self.make_rows(
            [79650.0, 79500.0, 79490.0, 79365.5],
            ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
            [45.0, 44.0, 42.0, 41.8],
            highs=[79660.0, 79520.0, 79510.0, 79600.0],
        )
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "R1_CONFIRMED_REJECTION")
        self.assertIsNotNone(result)
        self.assertIn("short_high_delta_pct", result)
        self.assertAlmostEqual(result["short_high_delta_pct"], (79600.0 / 79500.0 - 1) * 100, places=4)

    def test_pump_then_reversal_hypothesis_fires_from_history_only(self):
        prices = [79000.0, 79100.0, 79200.0, 79300.0, 79400.0, 79500.0, 79540.0, 79500.0, 79490.0, 79460.0]
        highs = [79020.0, 79110.0, 79220.0, 79320.0, 79430.0, 79570.0, 79600.0, 79600.0, 79600.0, 79600.0]
        df = self.make_rows(prices, highs=highs)
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "PUMP_THEN_REVERSAL")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["short_return_60m_pct"], short_config.SHORT_PUMP_REVERSAL_MIN_RETURN_60M_PCT)
        self.assertLessEqual(result["short_return_10m_pct"], short_config.SHORT_PUMP_REVERSAL_MAX_RETURN_10M_PCT)

    def test_pump_then_reversal_requires_prior_positive_hour(self):
        prices = [80000.0, 79900.0, 79800.0, 79700.0, 79600.0, 79500.0, 79480.0, 79460.0, 79430.0, 79400.0]
        highs = [80050.0, 80050.0, 80050.0, 80050.0, 80050.0, 80050.0, 80050.0, 80050.0, 80050.0, 80050.0]
        df = self.make_rows(prices, highs=highs)
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "PUMP_THEN_REVERSAL")
        self.assertIsNone(result)

    def test_oi_unwind_downturn_hypothesis_fires_on_defined_pattern(self):
        prices = [80000.0, 79990.0, 79950.0, 79890.0]
        df = self.make_rows(prices)
        df.loc[df.index[-1], "dOI"] = -0.15
        df.loc[df.index[-1], "doi_xmed"] = 1.3
        df.loc[df.index[-1], "vol_xmed"] = 1.8
        df.loc[df.index[-1], "taker_buy"] = 48.0
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "OI_UNWIND_DOWNTURN")
        self.assertIsNotNone(result)
        self.assertEqual(result["short_hypothesis"], "OI_UNWIND_DOWNTURN")

    def test_oi_unwind_rejects_nonnegative_oi_change(self):
        prices = [80000.0, 79990.0, 79950.0, 79890.0]
        df = self.make_rows(prices)
        df.loc[df.index[-1], "dOI"] = 0.05
        df.loc[df.index[-1], "doi_xmed"] = 1.3
        df.loc[df.index[-1], "vol_xmed"] = 1.8
        df.loc[df.index[-1], "taker_buy"] = 48.0
        prepared = prepare_short_features(df, short_config)
        result = evaluate_short_hypothesis(prepared.iloc[-1], short_config, "OI_UNWIND_DOWNTURN")
        self.assertIsNone(result)

    def test_disabled_hypotheses_not_emitted(self):
        # H1 can match mathematically but is disabled in the default research config.
        prices = [80000.0 * (1 - 0.001 * i) for i in range(31)]
        prepared = prepare_short_features(self.make_rows(prices), short_config)
        self.assertIsNone(generate_short_signal(prepared.iloc[-1], short_config))


if __name__ == "__main__":
    unittest.main()
