"""Bounded historical Binance Futures 1m-kline download for strict backtests."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pandas as pd


BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
ONE_MINUTE_MS = 60_000
PAGE_LIMIT = 1000


def fetch_binance_klines_for_period(
    symbol="BTCUSDT",
    start_time_ms=None,
    max_hold_minutes=1080,
    request_timeout=15,
):
    """Fetch only the entry-to-timeout window, never the entire history to now.

    `endTime` is inclusive. A maximum 1080-minute holding window needs at most
    1081 one-minute candles and therefore at most two REST calls.
    """
    if start_time_ms is None:
        raise ValueError("start_time_ms is required for a bounded backtest request")
    start_ms = int(start_time_ms)
    end_ms = start_ms + max(0, int(max_hold_minutes)) * ONE_MINUTE_MS
    current = start_ms
    all_rows = []

    while current <= end_ms:
        url = (
            f"{BINANCE_KLINES_URL}?symbol={symbol}&interval=1m&limit={PAGE_LIMIT}"
            f"&startTime={current}&endTime={end_ms}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Binance kline request failed for {symbol}: {exc}") from exc

        if not raw:
            break
        all_rows.extend(raw)
        if len(raw) < PAGE_LIMIT:
            break

        next_start = int(raw[-1][0]) + ONE_MINUTE_MS
        if next_start <= current:
            raise RuntimeError("Binance returned non-advancing kline timestamps")
        current = next_start

    if not all_rows:
        return pd.DataFrame(columns=["dt", "ts", "high", "low", "close"])

    df = pd.DataFrame(
        [
            {
                "dt": pd.to_datetime(candle[0], unit="ms", utc=True),
                "ts": pd.to_datetime(candle[0], unit="ms", utc=True).strftime("%Y-%m-%d %H:%M"),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
            }
            for candle in all_rows
        ]
    )
    return (
        df.drop_duplicates(subset="dt")
        .sort_values("dt")
        .reset_index(drop=True)
    )
