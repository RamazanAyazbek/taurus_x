from exit_logic import find_exit
from market_data import fetch_binance_klines_for_period
from movement_profile import calculate_movement_profile
from signal_logic import calculate_market_context, current_market_state, generate_signal


class TaurusRealisticStrictBacktester:
    def __init__(self, config):
        self.config = config
        self.tp_pct = config.TP_PCT
        self.sl_pct = config.SL_PCT
        self.be_pct = config.BE_PCT
        self.taker_fee = config.TAKER_FEE
        self.maker_fee = config.MAKER_FEE
        self.max_hold_minutes = config.TIMEOUT_MINUTES
        self.trades = []

    def _calculate_pnl(self, entry_price, exit_price, signal_type):
        if signal_type == "LONG":
            return (exit_price - entry_price) / entry_price * 100
        return (entry_price - exit_price) / entry_price * 100

    def _calculate_fee(self, exit_status):
        if not self.config.ENABLE_FEES:
            return 0

        if exit_status == "TIMEOUT":
            return self.taker_fee * 2

        return self.taker_fee + (
            self.maker_fee if exit_status == "WIN" else self.taker_fee
        )

    def _build_trade(self, curr, exit_info, signal_type, entry_price, movement_profile):
        hold_minutes = int(
            (exit_info["close_dt"] - curr["dt"]).total_seconds() / 60
        )
        pnl = self._calculate_pnl(entry_price, exit_info["price"], signal_type)
        fee = self._calculate_fee(exit_info["status"])

        trade = {
            "entry_time": curr["timestamp"],
            "exit_time": exit_info["close_local"].strftime("%Y-%m-%d %H:%M"),
            "type": signal_type,
            "entry_price": entry_price,
            "exit_price": exit_info["price"],
            "hold_minutes": hold_minutes,
            "net_pnl_pct": round(pnl - fee, 2),
            "result": exit_info["status"],
            "exit_reason": exit_info["reason"],
            "entry_dOI": curr["dOI"],
            "entry_dPrice": curr["dPrice"],
            "entry_volume": curr["volume"],
            "entry_taker_buy": curr["taker_buy"],
            "entry_zone": curr["in_zone"]
        }

        trade.update(movement_profile)
        return trade

    def run(self, df_logs, symbol=None):
        if df_logs.empty:
            print("Датафрейм логов пуст.")
            return

        symbol = symbol or self.config.SYMBOL
        last_closed_time = None
        state_active = False

        for _, curr in df_logs.iterrows():
            curr_dt = curr["dt"]

            if last_closed_time is not None and curr_dt <= last_closed_time:
                continue

            context = calculate_market_context(df_logs, curr, self.config)
            market_state = current_market_state(curr, self.config)

            if self.config.ENABLE_STATE_LOCK:
                if market_state and state_active:
                    continue
                if not market_state:
                    state_active = False

            signal_type = generate_signal(
                curr,
                context,
                market_state,
                self.config
            )

            if not signal_type:
                continue

            start_ms = int(curr_dt.timestamp() * 1000)
            df_klines = fetch_binance_klines_for_period(symbol, start_ms)

            if df_klines.empty:
                continue

            entry_price = curr["price"]

            exit_info = find_exit(
                df_klines,
                entry_price,
                signal_type,
                self.tp_pct,
                self.sl_pct,
                self.max_hold_minutes
            )

            if exit_info is None:
                continue

            movement_profile = {}
            if self.config.ENABLE_MOVEMENT_PROFILE:
                movement_profile = calculate_movement_profile(
                    df_klines,
                    entry_price,
                    curr_dt,
                    signal_type,
                    self.config.PROFILE_HORIZONS
                )

            self.trades.append(
                self._build_trade(
                    curr,
                    exit_info,
                    signal_type,
                    entry_price,
                    movement_profile
                )
            )

            last_closed_time = exit_info["close_dt"]
            state_active = True
