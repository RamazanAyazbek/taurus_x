"""Strict offline smoke/regression tests for experimental scenarios.

Uses the provided log to inspect actual past-only features and synthetic 1m
candles to exercise the entire engine. Synthetic PnL is NOT historical PnL.
"""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import config
import experiment_config as ex
from experiment_features import (
    parse_s1_band, support_proximity, taker_buy_change, select_delayed_entry,
)
from log_parser import parse_taurus_log
from run_experiments import run_all

ROOT = Path(__file__).resolve().parent


def fake_monitor_df():
    start = pd.Timestamp('2026-10-01 10:00', tz='Asia/Almaty')
    rows = []
    for i in range(34):
        when = start + pd.Timedelta(minutes=10*i)
        price = 78000 - i*80
        rows.append({
            'timestamp': when.strftime('%Y-%m-%d %H:%M'),
            'dt': when.tz_convert('UTC'),
            'dt_local': when.tz_localize(None),
            'price': float(price),
            'dPrice': -0.20 if i==30 else -0.01,
            'dOI': 0.6 if i==30 else 0.03,
            'doi_xmed': 2.0 if i==30 else 0.3,
            'volume': 5000.0 if i==30 else 200.0,
            'vol_xmed': 2.5 if i==30 else 0.3,
            'taker_buy': 40.0 if i==29 else (39.0 if i==30 else (48.0 if i==31 else 52.0)),
            'in_zone': 'S1[75.2k-75.4k]' if i in (30,31) else 'NONE',
        })
    return pd.DataFrame(rows)


def fake_candles(symbol, start_ms, max_hold):
    start = pd.Timestamp(start_ms, unit='ms', tz='UTC')
    confirmation = 78000 - 31*80
    bars=[]
    for i in range(18):
        op = confirmation * (0.997 if i >=3 else 1.0)
        low = 73800.0 if i==8 else 75000.0
        bars.append({'dt':start + pd.Timedelta(minutes=i), 'ts': str(i),
                     'open': op, 'high': 75800.0, 'low': low, 'close': 75400.0})
    return pd.DataFrame(bars)


class TestExperiments(unittest.TestCase):
    def test_parse_s1(self):
        self.assertEqual(parse_s1_band('S1[75.2k-75.4k]'), (75200,75400))
        self.assertIsNone(parse_s1_band('NONE'))
        self.assertIsNone(parse_s1_band('R1[75.2k-75.4k]'))

    def test_features_only_prior(self):
        frame=fake_monitor_df()
        support = support_proximity(frame, 31, float(frame.iloc[31]['price']), ex)
        taker = taker_buy_change(frame, 31, ex)
        self.assertTrue(support['support_near'])
        self.assertAlmostEqual(taker['taker_buy_delta_pp'], 8.0, places=4)
        self.assertTrue(taker['taker_buy_rising_fast'])
        # Future value edits may not affect historic signal's features.
        frame.loc[33,'taker_buy'] = 0.
        frame.loc[33,'in_zone'] = 'S1[50.0k-50.2k]'
        self.assertEqual(taker, taker_buy_change(frame, 31, ex))
        self.assertEqual(support, support_proximity(frame, 31, float(frame.iloc[31]['price']), ex))

    def test_broken_support_not_used(self):
        frame = fake_monitor_df()
        frame.loc[30:31,'in_zone'] = 'S1[76.0k-76.2k]'
        s=support_proximity(frame, 31, float(frame.iloc[31]['price']), ex)
        self.assertFalse(s['support_near'])
        self.assertIsNone(s['support_low'])

    def test_causality_preentry(self):
        frame=fake_monitor_df()
        dt=frame.iloc[31]['dt']
        candles=fake_candles('BTCUSDT', int(dt.timestamp()*1000), 1080)
        result=select_delayed_entry(candles, dt, frame.iloc[31]['price'], ex)
        self.assertEqual(result['entry_dt'], dt + pd.Timedelta(minutes=3))
        self.assertAlmostEqual(result['preentry_move_pct'], -0.3, places=3)
        self.assertTrue(result['preentry_fell_fast'])
        result_none=select_delayed_entry(candles[candles['dt'] != result['entry_dt']], dt,
                                         frame.iloc[31]['price'], ex)
        self.assertIsNone(result_none)

    def test_five_scenarios_execute_and_compare(self):
        df=fake_monitor_df()
        with tempfile.TemporaryDirectory() as td:
            results, summary = run_all(df, fetcher=fake_candles, output_dir=td)
            for case in ('baseline','support','taker','preentry','combined'):
                self.assertEqual(len(results[case]), 1, (case, results[case]))
                self.assertEqual(results[case][0]['exit_reason'], 'Take-Profit')
                self.assertTrue((Path(td)/f'{case}.csv').exists())
            self.assertTrue((Path(td)/'comparison.csv').exists())
            self.assertEqual(results['baseline'][0]['entry_price'], 78000-31*80)
            self.assertEqual(results['support'][0]['size_multiplier'],0.5)
            self.assertEqual(results['taker'][0]['size_multiplier'],0.5)
            self.assertEqual(results['preentry'][0]['size_multiplier'],0.5)
            self.assertEqual(results['combined'][0]['size_multiplier'],0.25)
            self.assertLess(results['preentry'][0]['entry_price'], results['baseline'][0]['entry_price'])
            self.assertEqual(int(summary['completed_trades'].sum()),5)
            self.assertEqual(results['baseline'][0]['net_pnl_pct'], results['support'][0]['net_pnl_pct'])
            self.assertEqual(results['baseline'][0]['net_pnl_pct'], results['taker'][0]['net_pnl_pct'])

    def test_market_data_open_field(self):
        from unittest.mock import patch
        from market_data import fetch_binance_klines_for_period
        start = int(pd.Timestamp('2026-10-01 12:00', tz='UTC').timestamp()*1000)
        raw = [
            [start, '100.1', '100.5', '99.7', '100.0', '5', 0, '0', 0, '0', '0', '0'],
            [start+60000, '100.3', '100.8', '99.0', '100.5', '5', 0, '0', 0, '0', '0', '0'],
        ]
        with patch('market_data._download_klines', return_value=raw):
            bars = fetch_binance_klines_for_period('BTCUSDT',start,4)
        self.assertEqual(len(bars),2)
        self.assertEqual(list(bars['open']),[100.1,100.3])
        self.assertEqual(list(bars['high']),[100.5,100.8])

    def test_candle_cache_reuses_same_snapshot(self):
        from candle_cache import CandleCache
        calls=[]
        def source(symbol, ms, minutes):
            calls.append((symbol,ms,minutes))
            return fake_candles(symbol, ms, minutes)
        with tempfile.TemporaryDirectory() as td:
            cache=CandleCache(directory=td,downloader=source)
            ms=int(pd.Timestamp('2026-10-01 12:00', tz='UTC').timestamp()*1000)
            a=cache('BTCUSDT',ms,1080)
            b=cache('BTCUSDT',ms,1080)
            self.assertEqual(len(calls),1)
            self.assertEqual(cache.cache_hits,1)
            self.assertEqual(len(a),len(b))
            b.loc[0,'open']=-1
            self.assertGreater(cache('BTCUSDT',ms,1080).iloc[0]['open'],0)

    def test_actual_06_nov_features_from_collector(self):
        df=parse_taurus_log(ROOT / config.LOG_FILE)
        matched = df.index[df['timestamp'] == '2026-11-06 19:30'].tolist()
        self.assertEqual(len(matched),1)
        idx=matched[0]
        support=support_proximity(df,idx,float(df.iloc[idx]['price']),ex)
        taker=taker_buy_change(df,idx,ex)
        self.assertTrue(support['support_near'])
        self.assertAlmostEqual(support['support_distance_pct'],0.2678,places=3)
        self.assertEqual(taker['taker_buy_delta_pp'],7.7)
        self.assertTrue(taker['taker_buy_rising_fast'])
        print('\nACTUAL LOG 06.11: near S1 =',support['support_near'],
              'distance=%',support['support_distance_pct'],
              'taker delta pp =',taker['taker_buy_delta_pp'])


if __name__ == '__main__':
    print('=== SYNTHETIC OFFLINE TESTS — THESE ARE NOT REAL HISTORICAL PNL ===', flush=True)
    unittest.main(verbosity=2)
