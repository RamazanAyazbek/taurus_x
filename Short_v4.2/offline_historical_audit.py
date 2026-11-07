"""NO Binance required: retrospective sizing of already-closed v7.3 CSV.

NOT a replay, not a substitute for run_experiments.py. Only A and B have
unmodified exit prices in these results; C cannot be evaluated without 1m OHLC.
"""
from pathlib import Path
import pandas as pd
from log_parser import parse_taurus_log
from experiment_features import support_proximity, taker_buy_change
import experiment_config as ex
import config


def audit():
    root = Path(__file__).resolve().parent
    df = parse_taurus_log(root / config.LOG_FILE)
    history = sorted((root / 'results').glob('short_v7.3.*.csv'))
    if not history:
        raise FileNotFoundError('Ожидается CSV v7.3 в results/')
    trades = pd.read_csv(history[0], encoding='utf-8-sig')
    by_ts = {str(ts): i for i, ts in enumerate(df['timestamp'])}
    records = []
    for _, trade in trades.iterrows():
        index = by_ts.get(str(trade['entry_time']))
        if index is None:
            raise ValueError(f'В Collector Log отсутствует confirmation: {trade["entry_time"]}')
        p = float(trade['entry_price'])
        sup = support_proximity(df, index, p, ex)
        taker = taker_buy_change(df, index, ex)
        a = ex.SUPPORT_SIZE_MULTIPLIER if sup['support_near'] else 1.0
        b = ex.TAKER_SIZE_MULTIPLIER if taker['taker_buy_rising_fast'] else 1.0
        net = float(trade['net_pnl_pct'])
        records.append({
            'signal_time': trade['signal_time'],
            'entry_time': trade['entry_time'],
            'exit_reason': trade['exit_reason'],
            'original_net_pct': net,
            'support_near': sup['support_near'],
            'support_distance_pct': sup['support_distance_pct'],
            'taker_buy_delta_pp': taker['taker_buy_delta_pp'],
            'taker_buy_rising_fast': taker['taker_buy_rising_fast'],
            'support_size': a, 'taker_size': b,
            'support_weighted_net_pct': round(net * a, 4),
            'taker_weighted_net_pct': round(net * b, 4),
            'a_plus_b_weighted_net_pct': round(net * max(a*b, ex.COMBINED_MIN_SIZE_MULTIPLIER), 4),
        })
    rows = pd.DataFrame(records)
    print('OFFLINE — только рескоринг сохранённых 15 исходов, без Binance 1m')
    print(rows[['entry_time', 'exit_reason', 'original_net_pct','support_near',
                'taker_buy_delta_pp', 'taker_buy_rising_fast',
                'support_weighted_net_pct', 'taker_weighted_net_pct']].to_string(index=False))
    for c in ['original_net_pct','support_weighted_net_pct',
              'taker_weighted_net_pct','a_plus_b_weighted_net_pct']:
        print(f'{c}: {rows[c].sum():+.4f} pp')
    print('S1 near:', int(rows['support_near'].sum()),
          'Taker rising:', int(rows['taker_buy_rising_fast'].sum()))
    print('Последний SL от 06.11 в исходном CSV отсутствует, следовательно в этой оценке НЕ участвует.')
    print('Сценарий preentry НЕ оценён: необходимы исторические Binance 1m OPEN.')
    out = root / 'results' / 'offline_audit_existing_15.csv'
    rows.to_csv(out, index=False, encoding='utf-8-sig')
    print('Report:',out)
    return rows


if __name__ == '__main__':
    audit()
