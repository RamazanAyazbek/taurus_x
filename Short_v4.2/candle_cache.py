"""On-disk Binance Futures 1m cache shared by all five scenario runs.

CSV.GZ only (no pickle). An in-process cache ensures all variants see the
same candles. Incomplete early downloads are refreshed on the next process run.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from market_data import fetch_binance_klines_for_period


class CandleCache:
    def __init__(self, directory='data/binance_1m_cache', downloader=None):
        self.directory = Path(directory)
        self.downloader = downloader or fetch_binance_klines_for_period
        self.memory = {}
        self.calls_to_binance = 0
        self.cache_hits = 0

    def __call__(self, symbol, start_time_ms, max_hold_minutes):
        key = (str(symbol).upper(), int(start_time_ms), int(max_hold_minutes))
        if key in self.memory:
            self.cache_hits += 1
            return self.memory[key].copy()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'{key[0]}_{key[1]}_{key[2]}m.csv.gz'
        if path.exists():
            frame = pd.read_csv(path, compression='gzip', parse_dates=['dt'])
            if not frame.empty:
                frame['dt'] = pd.to_datetime(frame['dt'], utc=True)
            # A partial snapshot could be stale tomorrow. Re-request it.
            expected_last = min(
                pd.Timestamp(key[1], unit='ms', tz='UTC') + pd.Timedelta(minutes=key[2]),
                pd.Timestamp.now(tz='UTC') - pd.Timedelta(minutes=3),
            )
            if not frame.empty and frame['dt'].max() >= expected_last:
                self.cache_hits += 1
                self.memory[key] = frame
                return frame.copy()
        self.calls_to_binance += 1
        frame = self.downloader(*key)
        if not frame.empty:
            temp_path = str(path) + '.tmp.gz'
            frame.to_csv(temp_path, compression='gzip', index=False)
            os.replace(temp_path, path)
        self.memory[key] = frame
        return frame.copy()
