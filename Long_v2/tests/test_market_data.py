import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import market_data


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _make_candle(ts):
    return [ts, "100", "101", "99", "100.5", "1", ts + 59999, "1", 1, "0", "0", "0"]


class BoundedFetchTests(unittest.TestCase):
    def test_1080_minute_window_uses_two_pages_max(self):
        start = 1_800_000_000_000
        calls = []

        def fake_urlopen(request, timeout=0):
            calls.append((request.full_url, timeout))
            query = parse_qs(urlparse(request.full_url).query)
            page_start = int(query["startTime"][0])
            page_end = int(query["endTime"][0])
            page_limit = int(query["limit"][0])
            times = list(range(page_start, min(page_end, page_start + (page_limit - 1) * 60_000) + 1, 60_000))
            return _FakeResponse([_make_candle(ts) for ts in times])

        with patch.object(market_data.urllib.request, "urlopen", side_effect=fake_urlopen):
            df = market_data.fetch_binance_klines_for_period(
                "BTCUSDT", start, max_hold_minutes=1080
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(df), 1081)
        self.assertEqual(int(df.iloc[-1]["dt"].timestamp() * 1000), start + 1080 * 60_000)


if __name__ == "__main__":
    unittest.main()
