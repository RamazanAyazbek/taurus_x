"""Five reproducible SHORT studies; no code or settings from live Reactor.

`TaurusShortBacktester` and its original `main.py` are kept unchanged. Here we
copy its execution semantics, adding only scenario-specific decisions and
research fields. Unfinished exits remain excluded exactly as in the source.
"""
import math
from types import SimpleNamespace

from backtester import TaurusShortBacktester
from exit_logic import find_exit
from market_data import fetch_binance_klines_for_period
from signal_logic import market_context, signal_rejection_reason, short_market_state
from experiment_features import support_proximity, taker_buy_change, select_delayed_entry
import experiment_config as ex

SCENARIOS = ('support', 'taker', 'preentry', 'combined')


class ExperimentalShortBacktester(TaurusShortBacktester):
    def __init__(self, config, scenario, candle_fetcher=None, settings=ex):
        if scenario not in SCENARIOS:
            raise ValueError(f'Unknown experimental scenario: {scenario}')
        super().__init__(config)
        self.scenario = scenario
        self.fetcher = candle_fetcher or fetch_binance_klines_for_period
        self.settings = settings
        self.diagnostics = {
            'qualified_confirmations': 0,
            'near_support': 0,
            'fast_taker_rise': 0,
            'fast_preentry_drop': 0,
            'delayed_price_unavailable': 0,
            'empty_candles': 0,
            'unresolved_exits': 0,
            'risk_reduced_trades': 0,
        }

    def run(self, df):
        last_closed_time = None
        state_active = False
        use_support = self.scenario in ('support', 'combined')
        use_taker = self.scenario in ('taker', 'combined')
        use_preentry = self.scenario in ('preentry', 'combined')
        for i in range(len(df)):
            curr = df.iloc[i]
            if last_closed_time is not None and curr['dt'] <= last_closed_time:
                continue
            market_state = short_market_state(curr, self.config)
            if self.config.ENABLE_STATE_LOCK:
                if market_state and state_active:
                    continue
                if not market_state:
                    state_active = False

            ctx = market_context(df, curr)
            rejection = signal_rejection_reason(curr, ctx, self.config)
            if rejection is not None:
                if rejection in self.filter_counts:
                    self.filter_counts[rejection] += 1
                continue
            entry_record = curr
            signal_time = curr['timestamp']
            confirmation_delay = 0.0
            confirmation_move_pct = 0.0
            confirmation_index = i
            if self.config.ENTRY_CONFIRMATION_ENABLED:
                if i + 1 >= len(df):
                    self.filter_counts['confirmation_gap'] += 1
                    continue
                confirmation = df.iloc[i + 1]
                confirmation_index = i + 1
                confirmation_delay = (confirmation['dt'] - curr['dt']).total_seconds() / 60.0
                if (confirmation_delay <= 0 or
                        confirmation_delay > self.config.CONFIRMATION_MAX_GAP_MINUTES):
                    self.filter_counts['confirmation_gap'] += 1
                    continue
                confirmation_move_pct = (float(confirmation['price']) / float(curr['price']) - 1.) * 100.
                max_rebound = self.config.CONFIRMATION_MAX_REBOUND_PCT * confirmation_delay / 10.0
                if confirmation_move_pct >= max_rebound:
                    self.filter_counts['confirmation_bounce'] += 1
                    continue
                if float(confirmation['taker_buy']) < self.config.CONFIRMATION_MIN_TAKER_BUY:
                    self.filter_counts['confirmation_taker_buy'] += 1
                    continue
                if (getattr(self.config, 'CONFIRMATION_MAX_TAKER_BUY_ENABLED', False) and
                        float(confirmation['taker_buy']) > self.config.CONFIRMATION_MAX_TAKER_BUY):
                    self.filter_counts['confirmation_taker_buy_max'] += 1
                    continue
                if getattr(self.config, 'CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED', False):
                    if confirmation_move_pct > -float(self.config.CONFIRMATION_MIN_DOWN_MOVE_PCT):
                        self.filter_counts['confirmation_direction'] += 1
                        continue
                entry_record = confirmation

            self.diagnostics['qualified_confirmations'] += 1
            confirmation_dt = entry_record['dt']
            confirmation_price = float(entry_record['price'])
            support = support_proximity(df, confirmation_index, confirmation_price, self.settings)
            taker = taker_buy_change(df, confirmation_index, self.settings)
            if support['support_near']:
                self.diagnostics['near_support'] += 1
            if taker['taker_buy_rising_fast']:
                self.diagnostics['fast_taker_rise'] += 1

            size = 1.0
            size_reasons = []
            if use_support and support['support_near']:
                size *= self.settings.SUPPORT_SIZE_MULTIPLIER
                size_reasons.append('near_S1')
            if use_taker and taker['taker_buy_rising_fast']:
                size *= self.settings.TAKER_SIZE_MULTIPLIER
                size_reasons.append('taker_rising')

            start_ms = int(confirmation_dt.timestamp() * 1000)
            try:
                candles = self.fetcher(
                    self.config.SYMBOL, start_ms, self.config.TIMEOUT_MINUTES
                )
            except Exception as exc:
                raise RuntimeError(
                    f'Binance 1m fetch failed at {entry_record["timestamp"]}: {exc}'
                ) from exc
            if candles.empty:
                self.diagnostics['empty_candles'] += 1
                continue

            entry_dt = confirmation_dt
            entry_price = confirmation_price
            preentry_move_pct = None
            preentry_fell_fast = False
            simulation_candles = candles
            if use_preentry:
                delayed = select_delayed_entry(candles, confirmation_dt, confirmation_price, self.settings)
                if delayed is None:
                    self.diagnostics['delayed_price_unavailable'] += 1
                    continue
                entry_dt = delayed['entry_dt']
                entry_price = delayed['entry_price']
                preentry_move_pct = delayed['preentry_move_pct']
                preentry_fell_fast = delayed['preentry_fell_fast']
                # Preserve source exit logic: it skips index 0 of this slice.
                simulation_candles = candles[candles['dt'] >= entry_dt].reset_index(drop=True)
                if preentry_fell_fast:
                    self.diagnostics['fast_preentry_drop'] += 1
                    size *= self.settings.PREENTRY_SIZE_MULTIPLIER
                    size_reasons.append('post_confirm_fall')

            if self.scenario == 'combined':
                size = max(size, float(self.settings.COMBINED_MIN_SIZE_MULTIPLIER))
            if size < 1:
                self.diagnostics['risk_reduced_trades'] += 1
            exit_info = find_exit(
                simulation_candles, entry_price, 'SHORT', self.config.TP_PCT,
                self.config.SL_PCT, self.config.TIMEOUT_MINUTES
            )
            if exit_info is None:
                self.diagnostics['unresolved_exits'] += 1
                continue  # TODO is intentionally deferred by user request.

            held = int((exit_info['close_dt'] - entry_dt).total_seconds() / 60)
            gross = self._pnl(entry_price, float(exit_info['price']))
            fee = self._fee(exit_info['status'])
            net = round(gross - fee, 2)  # same rounding as original
            excursion = self._excursion_stats(
                simulation_candles, entry_dt, exit_info['close_dt'], entry_price
            )
            self.trades.append({
                'signal_time': signal_time,
                'entry_time': entry_dt.tz_convert('Asia/Almaty').strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_info['close_local'].strftime('%Y-%m-%d %H:%M'),
                'type': 'SHORT',
                'entry_price': entry_price,
                'exit_price': exit_info['price'],
                'hold_minutes': held,
                'net_pnl_pct': net,
                'result': exit_info['status'],
                'exit_reason': exit_info['reason'],
                **excursion,
                'confirmation_delay_min': round(confirmation_delay, 1),
                'confirmation_move_pct': round(confirmation_move_pct, 3),
                'entry_dOI': entry_record['dOI'],
                'entry_dPrice': entry_record['dPrice'],
                'entry_volume': entry_record['volume'],
                'entry_taker_buy': entry_record['taker_buy'],
                'entry_zone': entry_record['in_zone'],
                # All additional fields are research annotations, never live orders.
                'scenario': self.scenario,
                'confirmation_time': entry_record['timestamp'],
                'confirmation_price': confirmation_price,
                **support,
                **taker,
                'preentry_move_pct': preentry_move_pct,
                'preentry_fell_fast': preentry_fell_fast,
                'size_multiplier': round(size, 6),
                'size_reasons': '+'.join(size_reasons),
                'weighted_net_pnl_pct': round(net * size, 4),
            })
            last_closed_time = exit_info['close_dt']
            state_active = True

        print(f'[{self.scenario}] filters={self.filter_counts} diagnostics={self.diagnostics}', flush=True)
        return self.trades
