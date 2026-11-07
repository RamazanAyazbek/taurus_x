"""Run baseline + all three independent SHORT experiments + optional combined.

Examples:
  python run_experiments.py
  python run_experiments.py --scenarios baseline,support,taker,preentry
  python self_test.py    # fully offline, no Binance access needed
"""
import argparse
import os
from pathlib import Path

import backtester as original_engine
import config
from candle_cache import CandleCache
from experimental_backtester import ExperimentalShortBacktester, SCENARIOS
from experiment_report import write_experiment_reports
from log_parser import parse_taurus_log

ALL_SCENARIOS = ('baseline',) + SCENARIOS


def run_all(df, scenarios=ALL_SCENARIOS, fetcher=None, output_dir='results/experiments'):
    """Also accepts deterministic candle fetcher for completely offline tests."""
    feed = fetcher or CandleCache()
    results = {}
    diagnostics = {}
    # Keep original source run() byte-for-byte for the reference.
    original_fetcher = original_engine.fetch_binance_klines_for_period
    original_engine.fetch_binance_klines_for_period = feed
    try:
        for scenario in scenarios:
            print(f'\n>>> {scenario.upper()} <<<', flush=True)
            if scenario == 'baseline':
                tester = original_engine.TaurusShortBacktester(config)
                tester.run(df)
                # Research columns only, do not modify original exported columns.
                trades = []
                for source_trade in tester.trades:
                    trade = source_trade.copy()
                    trade.update({
                        'scenario': 'baseline',
                        'confirmation_time': trade['entry_time'],
                        'confirmation_price': trade['entry_price'],
                        'size_multiplier': 1.0,
                        'weighted_net_pnl_pct': trade['net_pnl_pct'],
                    })
                    trades.append(trade)
                results[scenario] = trades
                diagnostics[scenario] = {}
            else:
                tester = ExperimentalShortBacktester(config, scenario, candle_fetcher=feed)
                tester.run(df)
                results[scenario] = tester.trades
                diagnostics[scenario] = tester.diagnostics
    finally:
        original_engine.fetch_binance_klines_for_period = original_fetcher
    summary = write_experiment_reports(results, diagnostics, output_dir)
    return results, summary


def main():
    parser = argparse.ArgumentParser(description='TAURUS SHORT | independent offline experiments')
    parser.add_argument('--scenarios', default=','.join(ALL_SCENARIOS),
                        help='Comma-separated: ' + ','.join(ALL_SCENARIOS))
    parser.add_argument('--output', default='results/experiments', help='Directory for scenario CSVs')
    parser.add_argument('--log', default=config.LOG_FILE, help='Collector log path')
    args = parser.parse_args()
    scenarios = [part.strip() for part in args.scenarios.split(',')]
    if len(set(scenarios)) != len(scenarios) or any(s not in ALL_SCENARIOS for s in scenarios):
        parser.error('Invalid or duplicate scenarios: ' + str(scenarios))
    if 'baseline' not in scenarios:
        parser.error('Include baseline for full comparable analysis')
    os.chdir(Path(__file__).resolve().parent)
    print('[+] Исходный config.py НЕ изменён; Reactor НЕ используется.')
    print('[+] Чтение Collector Log:', args.log)
    df = parse_taurus_log(args.log)
    if df.empty:
        raise SystemExit('Collector Log не распознан; проверяйте --log')
    print(f'[+] Наблюдений: {len(df)}, период {df.iloc[0]["timestamp"]} - {df.iloc[-1]["timestamp"]}')
    feed = CandleCache()
    run_all(df, scenarios, fetcher=feed, output_dir=args.output)
    print(f'[+] Запросов Binance за запуск: {feed.calls_to_binance}; cache hits: {feed.cache_hits}')


if __name__ == '__main__':
    main()
