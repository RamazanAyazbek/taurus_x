import unittest

import numpy as np
import pandas as pd

import config
from signal_logic import current_market_state, generate_signal, prepare_long_features


class LongSignalTests(unittest.TestCase):
    def setUp(self):
        self.good_row = pd.Series({
            "vol_xmed": 2.5,
            "volume": 9000.0,
            "doi_xmed": 2.0,
            "dOI": 0.45,
            "taker_buy": 50.0,
            "in_zone": "NONE",
        })
        self.good_context = {
            "previous_2h_return": 0.30,
            "previous_4h_return": 0.40,
            "previous_30m_return": 0.10,
            "previous_12h_return": 0.50,
            "previous_48h_return": 1.20,
            "long_sma_12h_slope_2h_pct": 0.08,
            "long_price_vs_sma_12h_pct": 0.20,
        }

    def test_positive_regime_passes(self):
        self.assertTrue(current_market_state(self.good_row, config))
        self.assertEqual(generate_signal(self.good_row, self.good_context, True, config), "LONG")

    def test_negative_4h_return_is_rejected(self):
        context = dict(self.good_context, previous_4h_return=-0.01)
        self.assertIsNone(generate_signal(self.good_row, context, True, config))

    def test_flat_or_falling_12h_sma_is_rejected(self):
        for slope in (0.02, 0.0, -0.1, None):
            context = dict(self.good_context, long_sma_12h_slope_2h_pct=slope)
            self.assertIsNone(generate_signal(self.good_row, context, True, config))

    def test_r1_resistance_entry_is_rejected(self):
        row = self.good_row.copy()
        row["in_zone"] = "R1[82.6k-82.9k]"
        self.assertIsNone(generate_signal(row, self.good_context, True, config))

    def test_weak_volume_ratio_is_rejected(self):
        row = self.good_row.copy()
        row["vol_xmed"] = 1.8
        self.assertFalse(current_market_state(row, config))

    def test_precompute_is_sorted_and_uses_past_only_history(self):
        idx = pd.date_range("2026-01-01", periods=3 * 24 * 6, freq="10min", tz="UTC")
        prices = 50000.0 + np.arange(len(idx)) * 2.0
        frame = pd.DataFrame({
            "dt": idx,
            "timestamp": idx.strftime("%Y-%m-%d %H:%M"),
            "price": prices,
            "vol_xmed": 3.0,
            "volume": 10000.0,
            "doi_xmed": 1.0,
            "dOI": 0.5,
            "dPrice": 0.1,
            "taker_buy": 50.0,
            "in_zone": "NONE",
        })
        prepared = prepare_long_features(frame.iloc[::-1], config)
        self.assertTrue(prepared["dt"].is_monotonic_increasing)
        self.assertIn("previous_48h_return", prepared.columns)
        self.assertIn("long_sma_12h_slope_2h_pct", prepared.columns)
        self.assertGreater(prepared.iloc[-1]["long_sma_12h_slope_2h_pct"], 0)
        self.assertAlmostEqual(prepared.iloc[-1]["previous_2h_return"],
                               (prices[-1] / prices[-13] - 1) * 100, places=6)


if __name__ == "__main__":
    unittest.main()
