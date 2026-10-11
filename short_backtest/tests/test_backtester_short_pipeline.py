import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
import long_config
import short_config
from backtester import TaurusRealisticStrictBacktester


class ShortBacktesterPipelineTests(unittest.TestCase):
    def test_short_candidate_flows_through_exit_engine(self):
        times = pd.date_range(
            "2026-08-27 16:10", periods=4, freq="10min", tz="Asia/Almaty"
        ).tz_convert("UTC")
        prices = [79650.0, 79500.0, 79490.0, 79365.5]
        logs = pd.DataFrame({
            "timestamp": [t.strftime("%Y-%m-%d %H:%M") for t in times],
            "dt": times,
            "dt_local": times.tz_convert("Asia/Almaty").tz_localize(None),
            "price": prices,
            "dPrice": [0.0] * 4,
            "dOI": [0.0] * 4,
            "doi_xmed": [1.0] * 4,
            "volume": [5000.0] * 4,
            "vol_xmed": [1.5] * 4,
            "taker_buy": [45.0, 44.0, 42.0, 41.8],
            "tag": ["NORMAL"] * 4,
            "in_zone": ["NONE", "NONE", "NONE", "R1[79.2k-79.5k]"],
        })
        entry_dt = times[-1]
        entry_price = prices[-1]
        candles = pd.DataFrame([
            {"dt": entry_dt, "ts": entry_dt.strftime("%Y-%m-%d %H:%M"),
             "high": entry_price, "low": entry_price, "close": entry_price},
            {"dt": entry_dt + pd.Timedelta(minutes=1),
             "ts": (entry_dt + pd.Timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"),
             "high": entry_price * 1.001, "low": entry_price * 0.98,
             "close": entry_price * 0.985},
        ])

        original_side = config.BACKTEST_SIDE
        original_r1 = short_config.ENABLE_SHORT_R1_REJECTION
        original_confirmed = short_config.ENABLE_SHORT_R1_CONFIRMED_REJECTION
        config.BACKTEST_SIDE = "SHORT"
        # This pipeline test is intentionally about the legacy R1 rule, not the new default.
        short_config.ENABLE_SHORT_R1_REJECTION = True
        short_config.ENABLE_SHORT_R1_CONFIRMED_REJECTION = False
        try:
            tester = TaurusRealisticStrictBacktester(
                config, long_config=long_config, short_config=short_config
            )
            with patch("backtester.fetch_binance_klines_for_period", return_value=candles):
                tester.run(logs, config.SYMBOL)
            self.assertEqual(len(tester.trades), 1)
            self.assertEqual(tester.trades[0]["type"], "SHORT")
            self.assertEqual(tester.trades[0]["short_hypothesis"], "R1_REJECTION")
            self.assertEqual(tester.trades[0]["result"], "WIN")
            self.assertAlmostEqual(tester.trades[0]["net_pnl_pct"], 1.43, places=2)
            self.assertEqual(tester.diagnostics["klines_fetch_failures"], 0)
        finally:
            config.BACKTEST_SIDE = original_side
            short_config.ENABLE_SHORT_R1_REJECTION = original_r1
            short_config.ENABLE_SHORT_R1_CONFIRMED_REJECTION = original_confirmed


if __name__ == "__main__":
    unittest.main()
