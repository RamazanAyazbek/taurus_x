import requests
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timezone, timedelta

# Настройка логирования важной информации в файл
logging.basicConfig(
    filename="trend_scanner.log",
    filemode="a",
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
    level=logging.INFO
)


class BinanceFuturesProScanner:
    def __init__(
            self,
            symbol: str = "BTCUSDT",
            timeframe: str = "1h",
            history_days: int = 30,  # Глубина истории за 1 месяц
            lookback_closed_candles: int = 3,  # Анализ последних 3 закрытых свечей
            timezone_offset: int = 5  # GMT+5 (Алматы / Екатеринбург)
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.history_limit = min(history_days * 24, 1000)
        self.lookback_closed_candles = lookback_closed_candles
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"

    def fetch_realtime_oi(self) -> float:
        """ Получает текущий Открытый Интерес в реальном времени без задержек """
        try:
            url = f"{self.base_url}/fapi/v1/openInterest"
            res = requests.get(url, params={"symbol": self.symbol}).json()
            return float(res['openInterest'])
        except Exception:
            return 0.0

    def fetch_market_snapshot(self) -> pd.DataFrame:
        """ Загружает глубокую историю свечей и OI """
        # 1. Загрузка свечей
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": self.history_limit}
        res_klines = requests.get(klines_url, params=params).json()

        df_klines = pd.DataFrame(res_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
        df_klines[cols] = df_klines[cols].astype(float)

        offset_hours = timedelta(hours=self.timezone_offset)
        tz_info = timezone(offset_hours)

        df_klines['time'] = (
            pd.to_datetime(df_klines['open_time'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 2. Загрузка Открытого Интереса (OI)
        oi_url = f"{self.base_url}/futures/data/openInterestHist"
        params_oi = {"symbol": self.symbol, "period": self.timeframe, "limit": self.history_limit}
        res_oi = requests.get(oi_url, params=params_oi).json()

        df_oi = pd.DataFrame(res_oi)
        df_oi['sumOpenInterest'] = df_oi['sumOpenInterest'].astype(float)

        df_oi['time'] = (
            pd.to_datetime(df_oi['timestamp'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 3. Синхронизация данных по времени
        df = pd.merge_asof(
            df_klines.sort_values('time'),
            df_oi[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi', 'taker_buy_volume': 'buy_volume'})

        df['sell_volume'] = df['volume'] - df['buy_volume']

        # Дельты изменений по свечам
        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100

        return df

    def calculate_monthly_baseline(self, df_closed: pd.DataFrame) -> dict:
        """
        Считает статистические метрики за прошлый месяц по закрытым свечам:
        - Использует ABS (модуль) для расчета реальной часовой активности OI и цены.
        """
        abs_oi_change = df_closed['oi_change_pct'].abs()
        abs_price_change = df_closed['price_change_pct'].abs()

        metrics = {
            # Объем
            "vol_mean": float(df_closed['volume'].mean()),
            "vol_median": float(df_closed['volume'].median()),
            "vol_std": float(df_closed['volume'].std()),

            # Абсолютная активность по OI (|dOI|)
            "abs_oi_mean": float(abs_oi_change.mean()),
            "abs_oi_median": float(abs_oi_change.median()),
            "abs_oi_std": float(abs_oi_change.std()),

            # Абсолютный размах цены (|dPrice|)
            "abs_price_mean": float(abs_price_change.mean()),
            "abs_price_median": float(abs_price_change.median()),
            "abs_price_std": float(abs_price_change.std())
        }
        return metrics

    def classify_candle_status(self, price_change_pct: float, oi_change_pct: float, vol_ratio: float) -> str:
        """ Классифицирует характер свечи на основе цены, OI и объема """
        is_high_volume = vol_ratio >= 1.3  # Превышение медианного объема на 30%+

        if is_high_volume:
            if price_change_pct > 0 and oi_change_pct > 0:
                return "🟢 BULLISH_IMPULSE"
            elif price_change_pct < 0 and oi_change_pct > 0:
                return "🔴 BEARISH_IMPULSE"
            elif price_change_pct > 0 and oi_change_pct < 0:
                return "⚡ SHORT_SQUEEZE"
            elif price_change_pct < 0 and oi_change_pct < 0:
                return "💥 LONG_LIQUIDATION"

        if price_change_pct > 0.3:
            return "📈 BULLISH_CANDLE"
        elif price_change_pct < -0.3:
            return "📉 BEARISH_CANDLE"

        return "⚪ NEUTRAL / FLAT"

    def analyze_live_market(self) -> dict:
        """ Главный метод анализа """
        df = self.fetch_market_snapshot()

        df_closed = df.iloc[:-1].copy()
        live_candle = df.iloc[-1]

        baseline = self.calculate_monthly_baseline(df_closed)
        last_closed_candle = df_closed.iloc[-1]

        # Данные закрывшейся свечи для отчета при смене часа
        last_closed_vol_ratio = last_closed_candle['volume'] / baseline['vol_median']
        last_closed_status = self.classify_candle_status(
            last_closed_candle['price_change_pct'],
            last_closed_candle['oi_change_pct'],
            last_closed_vol_ratio
        )

        closed_hour_summary = (
            f"✅ [HOUR CLOSED]: [{last_closed_candle['time'].strftime('%Y-%m-%d %H:00')}] "
            f"Close: {last_closed_candle['close']} | "
            f"Vol: {last_closed_candle['volume']:.1f} ({last_closed_vol_ratio:.2f}x Med) | "
            f"dPrice: {last_closed_candle['price_change_pct']:+.2f}% | "
            f"dOI: {last_closed_candle['oi_change_pct']:+.2f}% | "
            f"Tag: {last_closed_status}"
        )

        # Анализ открытой свечи
        candle_open_time = live_candle['time']
        now_time = datetime.now()

        minutes_passed = int((now_time - candle_open_time).total_seconds() // 60)
        minutes_passed = max(1, min(minutes_passed, 60))

        vol_current = live_candle['volume']
        projected_volume = (vol_current / minutes_passed) * 60

        live_price_pct = ((live_candle['close'] - live_candle['open']) / live_candle['open']) * 100

        realtime_oi = self.fetch_realtime_oi()
        last_closed_oi = last_closed_candle['oi']

        if realtime_oi > 0 and last_closed_oi > 0:
            live_oi_pct = ((realtime_oi - last_closed_oi) / last_closed_oi) * 100
        else:
            live_oi_pct = ((live_candle['oi'] - last_closed_oi) / last_closed_oi) * 100

        projected_vol_ratio = projected_volume / baseline['vol_median']
        live_status = self.classify_candle_status(live_price_pct, live_oi_pct, projected_vol_ratio)

        # Детекция аномалий по абсолютным порогам
        is_volume_anomalous = projected_volume >= (baseline['vol_median'] * 1.5)
        is_oi_anomalous = abs(live_oi_pct) >= (baseline['abs_oi_median'] * 2.0)

        signal_code = "NO_SIGNAL"
        if is_volume_anomalous and is_oi_anomalous:
            signal_code = live_status

        return {
            "candle_open_str": candle_open_time.strftime("%Y-%m-%d %H:00"),
            "timestamp_now": now_time.strftime("%Y-%m-%d %H:%M"),
            "minutes_passed": minutes_passed,
            "price": live_candle['close'],
            "live_price_pct": round(live_price_pct, 2),
            "live_oi_pct": round(live_oi_pct, 2),
            "vol_actual": round(vol_current, 1),
            "vol_projected_ratio": round(projected_vol_ratio, 2),
            "live_status": live_status,
            "signal_code": signal_code,
            "closed_hour_summary": closed_hour_summary
        }


if __name__ == "__main__":
    scanner = BinanceFuturesProScanner(
        symbol="BTCUSDT",
        timeframe="1h",
        history_days=30,
        lookback_closed_candles=3,
        timezone_offset=5
    )

    print("=" * 90)
    print(f" Starting PRO-Scanner {scanner.symbol} | Calculating 30-day baseline...")
    print("=" * 90)

    df_init = scanner.fetch_market_snapshot()
    df_closed = df_init.iloc[:-1]
    base_stats = scanner.calculate_monthly_baseline(df_closed)

    recent_3 = df_closed.tail(3)

    history_lines = []
    for _, row in recent_3.iterrows():
        candle_time = row['time'].strftime('%Y-%m-%d %H:%M')
        vol_ratio = row['volume'] / base_stats['vol_median']
        p_change = row['price_change_pct']
        oi_change = row['oi_change_pct']
        tag = scanner.classify_candle_status(p_change, oi_change, vol_ratio)

        line = (
            f"  • [{candle_time}] "
            f"Close: {row['close']} | "
            f"Vol: {row['volume']:.1f} ({vol_ratio:.2f}x Med) | "
            f"dPrice: {p_change:+.2f}% | "
            f"dOI: {oi_change:+.2f}% | "
            f"Tag: {tag}"
        )
        history_lines.append(line)

    history_str = "\n".join(history_lines)

    init_log = (
        f"--- 30-DAY MONTHLY BASELINE STATISTICS ---\n"
        f"Volume           : Mean={base_stats['vol_mean']:.1f}, Median={base_stats['vol_median']:.1f}, Std={base_stats['vol_std']:.1f}\n"
        f"|dOI| Activity   : Mean={base_stats['abs_oi_mean']:.3f}%, Median={base_stats['abs_oi_median']:.3f}%, Std={base_stats['abs_oi_std']:.3f}%\n"
        f"|dPrice| Volat.  : Mean={base_stats['abs_price_mean']:.3f}%, Median={base_stats['abs_price_median']:.3f}%, Std={base_stats['abs_price_std']:.3f}%\n"
        f"------------------------------------------------\n"
        f"--- LAST 3 CLOSED HOURS CONTEXT ---\n"
        f"{history_str}\n"
        f"------------------------------------------------"
    )

    logging.info(init_log)
    print("💾 Monthly baseline & 3H history recorded to trend_scanner.log:\n")
    print(init_log)

    print("\nMonitoring live market every 10 minutes...\n")

    last_signal_key = None
    current_active_hour = None

    while True:
        try:
            data = scanner.analyze_live_market()

            # При наступлении нового часа выводим детальную сводку закрывшейся свечи
            if current_active_hour is not None and data['candle_open_str'] != current_active_hour:
                print(f"\n{data['closed_hour_summary']}\n")
                logging.info(data['closed_hour_summary'])

            current_active_hour = data['candle_open_str']

            # Краткий вывод без 3H Context
            status_suffix = f" | Status: {data['live_status']}" if data['signal_code'] != "NO_SIGNAL" else ""

            console_output = (
                f"[{data['timestamp_now']} | {data['minutes_passed']}m/60m] "
                f"BTC: {data['price']} ({data['live_price_pct']:+.2f}%) | "
                f"ΔOI: {data['live_oi_pct']:+.2f}% | "
                f"Vol: {data['vol_actual']:.0f} (Proj: {data['vol_projected_ratio']}x Med)"
                f"{status_suffix}"
            )
            print(console_output)

            # Логирование аномальных сигналов
            if data['signal_code'] != "NO_SIGNAL":
                current_key = f"{data['timestamp_now']}_{data['signal_code']}"
                if current_key != last_signal_key:
                    sig_log = (
                        f"SIGNAL: {data['signal_code']} | "
                        f"Price: {data['price']} ({data['live_price_pct']}%) | "
                        f"dOI: {data['live_oi_pct']}% | "
                        f"VolRatio: {data['vol_projected_ratio']}x"
                    )
                    logging.info(sig_log)
                    print(f"\n💾 [LOGGED TO FILE]: {sig_log}\n")
                    last_signal_key = current_key

        except Exception as e:
            err_msg = f"Scan error: {str(e)}"
            print(f"❌ {err_msg}")
            logging.error(err_msg)

        time.sleep(600)