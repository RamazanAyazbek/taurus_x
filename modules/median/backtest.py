import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone

# Настройка файлового логера для телеметрии сделок
logging.basicConfig(
    filename="flight_recorder.log",
    filemode="w",  # "w" — перезаписывать файл при каждом прогоне
    format="%(message)s",
    encoding="utf-8",
    level=logging.INFO
)


class FlightRecorderBacktester:
    def __init__(
            self,
            symbol: str = "BTCUSDT",
            timeframe: str = "1h",
            backtest_days: int = 90,
            baseline_days: int = 30,
            history_context_len: int = 3,  # Сколько свечей ДО входа логировать
            rr_ratio: float = 1.5,
            min_sl_pct: float = 0.5,
            max_sl_pct: float = 1.8,
            max_hold_hours: int = 12,
            fee_pct: float = 0.04
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.backtest_days = backtest_days
        self.baseline_days = baseline_days
        self.baseline_hours = baseline_days * 24
        self.history_context_len = history_context_len
        self.rr_ratio = rr_ratio
        self.min_sl_pct = min_sl_pct
        self.max_sl_pct = max_sl_pct
        self.max_hold_hours = max_hold_hours
        self.fee_pct = fee_pct
        self.base_url = "https://fapi.binance.com"

    def fetch_historical_data(self) -> pd.DataFrame:
        total_days = self.backtest_days + self.baseline_days
        total_hours = total_days * 24

        print(f"📥 Загрузка данных за {total_days} дней ({total_hours} свечей)...")

        # 1. Свечи (Klines)
        all_klines = []
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)

        while len(all_klines) < total_hours:
            limit = min(1500, total_hours - len(all_klines))
            url = f"{self.base_url}/fapi/v1/klines"
            params = {"symbol": self.symbol, "interval": self.timeframe, "limit": limit, "endTime": end_time}
            res = requests.get(url, params=params).json()
            if not res or isinstance(res, dict): break
            all_klines = res + all_klines
            end_time = res[0][0] - 1

        df_k = pd.DataFrame(all_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume']
        df_k[cols] = df_k[cols].astype(float)
        df_k['time'] = pd.to_datetime(df_k['open_time'], unit='ms', utc=True)

        # 2. Открытый Интерес (OI)
        all_oi = []
        end_time_oi = int(datetime.now(timezone.utc).timestamp() * 1000)

        while len(all_oi) < total_hours:
            limit = min(500, total_hours - len(all_oi))
            url = f"{self.base_url}/futures/data/openInterestHist"
            params = {"symbol": self.symbol, "period": self.timeframe, "limit": limit, "endTime": end_time_oi}
            res = requests.get(url, params=params).json()
            if not res or isinstance(res, dict): break
            all_oi = res + all_oi
            end_time_oi = int(res[0]['timestamp']) - 1

        df_o = pd.DataFrame(all_oi)
        df_o['sumOpenInterest'] = df_o['sumOpenInterest'].astype(float)
        df_o['time'] = pd.to_datetime(df_o['timestamp'], unit='ms', utc=True)

        # 3. Синхронизация и Индикаторы
        df = pd.merge_asof(
            df_k.sort_values('time'),
            df_o[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi'})

        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100

        # Добавляем 50 EMA для понимания тренда
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

        return df.dropna().reset_index(drop=True)

    def classify_candle_status(self, p_change: float, oi_change: float, vol_ratio: float) -> str:
        if vol_ratio >= 1.3:
            if p_change > 0 and oi_change > 0:
                return "🟢 BULLISH_IMPULSE"
            elif p_change < 0 and oi_change > 0:
                return "🔴 BEARISH_IMPULSE"
            elif p_change > 0 and oi_change < 0:
                return "⚡ SHORT_SQUEEZE"
            elif p_change < 0 and oi_change < 0:
                return "💥 LONG_LIQUIDATION"
        return "⚪ NEUTRAL / FLAT"

    def run_backtest(self):
        df = self.fetch_historical_data()
        trades = []
        in_trade = False
        active_trade = None

        print(f"\n🚀 Запуск симуляции с детальной записью телеметрии в flight_recorder.log...\n")
        logging.info("==========================================================================================")
        logging.INFO and logging.info(
            "  FLIGHT RECORDER (ЧЕРНЫЙ ЯЩИК) — ДЕТАЛИЗАЦИЯ ВСЕХ СДЕЛОК СТРАТЕГИИ BINANCE FUTURES")
        logging.info("==========================================================================================\n")

        start_idx = self.baseline_hours
        trade_id = 0

        for i in range(start_idx, len(df)):
            current_row = df.iloc[i]

            # --- 1. ЕСЛИ МЫ В СДЕЛКЕ: МОНИТОРИНГ ЖИЗНИ ОРДЕРА ПО СВЕЧАМ ---
            if in_trade:
                trade_dir = active_trade['direction']
                tp_price = active_trade['tp_price']
                sl_price = active_trade['sl_price']
                entry_price = active_trade['entry_price']
                hours_held = i - active_trade['entry_idx']

                # Записываем телеметрию текущего часа жизненного цикла
                vol_ratio = current_row['volume'] / active_trade['baseline_vol_med']
                step_log = (
                    f"   [+ {hours_held}h] {current_row['time'].strftime('%Y-%m-%d %H:00')} | "
                    f"Close: {current_row['close']} | "
                    f"High: {current_row['high']} | Low: {current_row['low']} | "
                    f"dPrice: {current_row['price_change_pct']:+.2f}% | "
                    f"dOI: {current_row['oi_change_pct']:+.2f}% | "
                    f"VolRatio: {vol_ratio:.2f}x"
                )
                active_trade['lifecycle_logs'].append(step_log)

                exit_type = None
                exit_price = None

                # Проверка выхода
                if trade_dir == "LONG":
                    if current_row['low'] <= sl_price:
                        exit_type = "STOP_LOSS"
                        exit_price = sl_price
                    elif current_row['high'] >= tp_price:
                        exit_type = "TAKE_PROFIT"
                        exit_price = tp_price
                elif trade_dir == "SHORT":
                    if current_row['high'] >= sl_price:
                        exit_type = "STOP_LOSS"
                        exit_price = sl_price
                    elif current_row['low'] <= tp_price:
                        exit_type = "TAKE_PROFIT"
                        exit_price = tp_price

                if not exit_type and hours_held >= self.max_hold_hours:
                    exit_type = "TIMEOUT"
                    exit_price = current_row['close']

                if exit_type:
                    if trade_dir == "LONG":
                        raw_pnl = ((exit_price - entry_price) / entry_price) * 100
                    else:
                        raw_pnl = ((entry_price - exit_price) / entry_price) * 100

                    net_pnl = raw_pnl - (self.fee_pct * 2)

                    # ЗАПИСЬ СДЕЛКИ В ФАЙЛ ЛОГА
                    self.log_full_trade_story(active_trade, current_row, exit_type, exit_price, hours_held, net_pnl)

                    active_trade.update({
                        "exit_time": current_row['time'],
                        "exit_price": exit_price,
                        "exit_type": exit_type,
                        "hours_held": hours_held,
                        "net_pnl_pct": round(net_pnl, 2)
                    })
                    trades.append(active_trade)
                    in_trade = False
                    active_trade = None

                continue

            # --- 2. ЕСЛИ НЕ В СДЕЛКЕ: ПОИСК ТОЧКИ А ---
            baseline_window = df.iloc[i - self.baseline_hours: i]
            vol_median = baseline_window['volume'].median()
            abs_oi_median = baseline_window['oi_change_pct'].abs().median()

            vol_ratio = current_row['volume'] / vol_median
            p_change = current_row['price_change_pct']
            oi_change = current_row['oi_change_pct']

            is_vol_anomalous = current_row['volume'] >= (vol_median * 1.5)
            is_oi_anomalous = abs(oi_change) >= (abs_oi_median * 2.0)

            if is_vol_anomalous and is_oi_anomalous:
                tag = self.classify_candle_status(p_change, oi_change, vol_ratio)

                direction = None
                if tag in ["🟢 BULLISH_IMPULSE", "⚡ SHORT_SQUEEZE"]:
                    direction = "LONG"
                elif tag in ["🔴 BEARISH_IMPULSE", "💥 LONG_LIQUIDATION"]:
                    direction = "SHORT"

                if direction:
                    trade_id += 1
                    entry_price = current_row['close']

                    # Расчет уровней
                    if direction == "LONG":
                        sl_price = current_row['low'] * 0.9995
                        raw_risk_pct = ((entry_price - sl_price) / entry_price) * 100
                        risk_pct = max(self.min_sl_pct, min(raw_risk_pct, self.max_sl_pct))
                        sl_price = entry_price * (1 - risk_pct / 100)
                        tp_price = entry_price * (1 + (risk_pct * self.rr_ratio) / 100)
                    else:
                        sl_price = current_row['high'] * 1.0005
                        raw_risk_pct = ((sl_price - entry_price) / entry_price) * 100
                        risk_pct = max(self.min_sl_pct, min(raw_risk_pct, self.max_sl_pct))
                        sl_price = entry_price * (1 + risk_pct / 100)
                        tp_price = entry_price * (1 - (risk_pct * self.rr_ratio) / 100)

                    # Собираем контекст за N свечей ДО сигнала
                    pre_history = []
                    for h_idx in range(i - self.history_context_len, i):
                        h_row = df.iloc[h_idx]
                        h_vol_ratio = h_row['volume'] / vol_median
                        pre_history.append(
                            f"   [HIST {- (i - h_idx)}h] {h_row['time'].strftime('%Y-%m-%d %H:00')} | "
                            f"Close: {h_row['close']} | dPrice: {h_row['price_change_pct']:+.2f}% | "
                            f"dOI: {h_row['oi_change_pct']:+.2f}% | VolRatio: {h_vol_ratio:.2f}x"
                        )

                    in_trade = True
                    active_trade = {
                        "trade_id": trade_id,
                        "entry_idx": i,
                        "entry_time": current_row['time'],
                        "signal_tag": tag,
                        "direction": direction,
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "risk_pct": round(risk_pct, 2),
                        "baseline_vol_med": vol_median,
                        "baseline_oi_med": abs_oi_median,
                        "signal_vol_ratio": vol_ratio,
                        "signal_p_change": p_change,
                        "signal_oi_change": oi_change,
                        "ema50_trend": "ABOVE_EMA" if entry_price > current_row['ema50'] else "BELOW_EMA",
                        "pre_history_logs": pre_history,
                        "lifecycle_logs": []
                    }

        self.print_summary(trades)

    def log_full_trade_story(self, trade: dict, exit_row, exit_type: str, exit_price: float, hours_held: int,
                             net_pnl: float):
        """ Записывает полную анатомию одной сделки в файл flight_recorder.log """
        status_icon = "✅ PROFIT" if net_pnl > 0 else "❌ LOSS"

        log_entry = [
            "--------------------------------------------------------------------------------------------------------",
            f"ORDER #{trade['trade_id']} | {trade['direction']} | SIGNAL: {trade['signal_tag']} | RESULT: {status_icon} ({net_pnl:+.2f}%)",
            "--------------------------------------------------------------------------------------------------------",
            "1️⃣ КОНТЕКСТ РЫНКА ДО СИГНАЛА (ПРЕДИСТОРИЯ):",
            *trade['pre_history_logs'],
            "",
            "2️⃣ ТОЧКА ВХОДА (ТОЧКА А) И СОСТОЯНИЕ ИНДИКАТОРОВ:",
            f"   • Время входа        : {trade['entry_time'].strftime('%Y-%m-%d %H:00')}",
            f"   • Входная цена (Close): {trade['entry_price']}",
            f"   • Take Profit        : {trade['tp_price']:.2f} | Stop Loss: {trade['sl_price']:.2f} (Риск: {trade['risk_pct']}%)",
            f"   • Сигнальная свеча   : dPrice = {trade['signal_p_change']:+.2f}%, dOI = {trade['signal_oi_change']:+.2f}%, VolRatio = {trade['signal_vol_ratio']:.2f}x (от медианы)",
            f"   • Положение к EMA50  : {trade['ema50_trend']}",
            "",
            "3️⃣ РАЗВИТИЕ СИТУАЦИИ ВО ВРЕМЯ СДЕЛКИ (ПОСВЕЧНЫЙ МОНИТОРИНГ):",
            *trade['lifecycle_logs'],
            "",
            "4️⃣ ЗАКРЫТИЕ ОРДЕРА (ТОЧКА Б):",
            f"   • Время выходя       : {exit_row['time'].strftime('%Y-%m-%d %H:00')} (продержали {hours_held} часов)",
            f"   • Цена выхода        : {exit_price}",
            f"   • Причина закрытия   : {exit_type}",
            f"   • Чистый PnL         : {net_pnl:+.2f}% (с учетом комиссии)",
            "--------------------------------------------------------------------------------------------------------\n\n"
        ]
        logging.info("\n".join(log_entry))

    def print_summary(self, trades: list):
        if not trades:
            print("❌ Сделок не обнаружено.")
            return

        df_tr = pd.DataFrame(trades)
        total_trades = len(df_tr)
        wins = df_tr[df_tr['net_pnl_pct'] > 0]
        losses = df_tr[df_tr['net_pnl_pct'] <= 0]

        winrate = (len(wins) / total_trades) * 100
        total_pnl = df_tr['net_pnl_pct'].sum()

        print("=" * 70)
        print("💾 ВСЯ ТЕЛЕМЕТРИЯ СДЕЛАК ЗАПИСАНА В ФАЙЛ: flight_recorder.log")
        print("=" * 70)
        print(f"Всего зафиксировано сделок : {total_trades}")
        print(f"Винрейт (Win Rate)          : {winrate:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"Общий кумулятивный PnL      : {total_pnl:+.2f}%")
        print("=" * 70)
        print("💡 Откройте файл 'flight_recorder.log', чтобы изучить поведение рыночных показателей!")


if __name__ == "__main__":
    backtester = FlightRecorderBacktester(
        symbol="BTCUSDT",
        timeframe="1h",
        backtest_days=90,
        baseline_days=30,
        history_context_len=3,  # Фиксировать 3 свечи ДО входа
        rr_ratio=1.5,
        min_sl_pct=0.5,
        max_sl_pct=1.8,
        max_hold_hours=12
    )
    backtester.run_backtest()