"""Scenario CSV ledgers, robust comparison with comparable notional sizing."""
from pathlib import Path
import pandas as pd

ORIGINAL_COLUMNS = [
    'signal_time','entry_time','exit_time','type','entry_price','exit_price',
    'hold_minutes','net_pnl_pct','exit_reason','mfe_pct','mae_pct',
    'mfe_time_min','mae_time_min','confirmation_delay_min',
    'confirmation_move_pct','entry_dOI','entry_dPrice','entry_volume',
    'entry_taker_buy','entry_zone',
]
EXTRA_COLUMNS = [
    'scenario','confirmation_time','confirmation_price',
    'support_low','support_high','support_distance_pct',
    'support_observed_at','support_near',
    'taker_buy_lookback','taker_buy_delta_pp','taker_buy_rising_fast',
    'taker_buy_lookback_time','preentry_move_pct','preentry_fell_fast',
    'size_multiplier','size_reasons','weighted_net_pnl_pct',
]


def write_experiment_reports(results, diagnostics, output_directory):
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    base_signals = set(t['signal_time'] for t in results.get('baseline', []))
    overview = []
    for scenario, trades in results.items():
        df = pd.DataFrame(trades)
        for col in ORIGINAL_COLUMNS + EXTRA_COLUMNS:
            if col not in df.columns:
                df[col] = pd.Series(dtype='object')
        df[ORIGINAL_COLUMNS + EXTRA_COLUMNS].to_csv(
            output / f'{scenario}.csv', index=False, encoding='utf-8-sig'
        )
        if df.empty:
            won, lost, timed = 0, 0, 0
            winrate, total, weighted = None, 0., 0.
            pf = None
        else:
            won = int((df['exit_reason'] == 'Take-Profit').sum())
            lost = int((df['exit_reason'] == 'Stop-Loss').sum())
            timed = int((df['exit_reason'] == 'Timeout').sum())
            winrate = won / (won+lost) * 100 if won+lost else None
            total = float(df['net_pnl_pct'].sum())
            weighted = float(df['weighted_net_pnl_pct'].sum())
            pos = df.loc[df['weighted_net_pnl_pct'] > 0, 'weighted_net_pnl_pct'].sum()
            neg = df.loc[df['weighted_net_pnl_pct'] < 0, 'weighted_net_pnl_pct'].sum()
            pf = float(pos / (-neg)) if neg < 0 else None
        signals = {t['signal_time'] for t in trades}
        meta = diagnostics.get(scenario, {})
        overview.append({
            'scenario': scenario,
            'completed_trades': len(trades),
            'tp': won,
            'sl': lost,
            'timeout': timed,
            'winrate_tp_over_tp_sl_pct': round(winrate, 2) if winrate is not None else None,
            'sum_net_pct_unscaled': round(total, 4),
            'sum_net_pct_weighted': round(weighted, 4),
            'weighted_profit_factor': round(pf, 4) if pf is not None else None,
            'matched_baseline_signals': len(signals & base_signals),
            'baseline_signals_missing': len(base_signals - signals),
            'additional_signals_vs_baseline': len(signals - base_signals),
            'qualifying_confirmations': meta.get('qualified_confirmations'),
            'near_support_candidates': meta.get('near_support'),
            'fast_taker_rise_candidates': meta.get('fast_taker_rise'),
            'fast_preentry_drop_candidates': meta.get('fast_preentry_drop'),
            'reduced_risk_candidates': meta.get('risk_reduced_trades'),
            'unresolved_exits_excluded': meta.get('unresolved_exits'),
            'empty_candles_excluded': meta.get('empty_candles'),
            'preentry_candle_missing_excluded': meta.get('delayed_price_unavailable'),
        })
    summary_df = pd.DataFrame(overview)
    summary_df.to_csv(output / 'comparison.csv', index=False, encoding='utf-8-sig')
    print('\n=== SCENARIO COMPARISON ===')
    display_columns = [
        'scenario', 'completed_trades', 'tp', 'sl', 'timeout',
        'winrate_tp_over_tp_sl_pct', 'sum_net_pct_unscaled',
        'sum_net_pct_weighted', 'baseline_signals_missing',
        'additional_signals_vs_baseline',
    ]
    print(summary_df[display_columns].to_string(index=False))
    print('\nSum weighted % = net return weighted by hypothetical size relative to ONE constant notional.\n'
          'NOT equity growth, not margin ROI, no lot-size rounding, no funding.')
    print(f'\nSaved CSVs in: {output.resolve()}')
    return summary_df
