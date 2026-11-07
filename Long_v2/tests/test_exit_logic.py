import unittest
import pandas as pd
from exit_logic import find_exit


class BreakevenTests(unittest.TestCase):
    def test_be_trigger_applies_on_next_candle(self):
        dt = pd.date_range("2026-01-01", periods=4, freq="1min", tz="UTC")
        candles = pd.DataFrame({
            "dt": dt,
            "high": [100, 101.2, 100.4, 100.2],
            "low": [100, 100.2, 99.9, 99.8],
            "close": [100, 100.5, 100.0, 100.0],
        })
        result = find_exit(candles, 100, "LONG", 1.5, 0.7, 10, be_pct=1.1)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "BE")
        self.assertEqual(result["price"], 100)

    def test_be_off_preserves_regular_stop(self):
        dt = pd.date_range("2026-01-01", periods=3, freq="1min", tz="UTC")
        candles = pd.DataFrame({
            "dt": dt,
            "high": [100, 101.2, 100.2],
            "low": [100, 100.2, 99.0],
            "close": [100, 100.5, 99.5],
        })
        result = find_exit(candles, 100, "LONG", 1.5, 0.7, 10, be_pct=None)
        self.assertEqual(result["status"], "LOSS")


if __name__ == "__main__":
    unittest.main()
