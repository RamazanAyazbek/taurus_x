import requests
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timezone, timedelta

# Настройка логирования
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
            history_days: int = 30,  # 30 дней истории для точности медианы
            lookback_closed_candles: int = 3,  # Последние 3 свечи в контекст
            timezone_offset: int = 5  # GMT+5
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.history_limit = min(history_days * 24, 1000)
        self.lookback_closed_candles = lookback_closed_candles
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"

    def fetch_realtime_oi(self) -> float:
        """ Получает текущий Открытый Интерес без задержек """
        try:
            url = f"{self.base_url}/fapi/v1/openInterest"
            res = requests.get(url, params={"symbol": self.symbol}).json()
            return float(res['openInterest'])
        except Exception:
            return 0.0

    def fetch_market_snapshot(self) -> pd.DataFrame:
        """ Загружает свечи и OI из Binance API """
        # 1. Свечи
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

        # 2. История OI
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

        # 3. Объединение по времени
        df = pd.merge_asof(
            df_klines.sort_values('time'),
            df_oi[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi', 'taker_buy_volume': 'buy_volume'})

        df['sell_volume'] = df['volume'] - df['buy_volume']

        # Изменения в %
        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100

        return df

    def calculate_baseline(self, df_closed: pd.DataFrame) -> dict:
        """ Расчет медианы и стандартных метрик за 30 дней """
        abs_oi_change = df_closed['oi_change_pct'].abs()
        abs_price_change = df_closed['price_change_pct'].abs()

        return {
            "vol_mean": float(df_closed['volume'].mean()),
            "vol_median": float(df_closed['volume'].median()),
            "vol_std": float(df_closed['volume'].std()),
            "abs_oi_median": float(abs_oi_change.median()),
            "abs_price_median": float(abs_price_change.median())
        }

    def classify_candle_status(self, price_change_pct: float, oi_change_pct: float, vol_ratio: float) -> str:
        """ Присвоение тегов свече """
        is_high_volume = vol_ratio >= 1.3

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
        """ Анализ закрытых свечей и текущего рынка """
        df = self.fetch_market_snapshot()

        df_closed = df.iloc[:-1].copy()
        live_candle = df.iloc[-1]

        baseline = self.calculate_baseline(df_closed)
        last_closed_candle = df_closed.iloc[-1]

        # Контекст последних 3 закрытых часов
        recent_3 = df_closed.tail(self.lookback_closed_candles)
        context_lines = []
        for _, row in recent_3.iterrows():
            c_time = row['time'].strftime('%H:00')  # Исправлено (%H:00 вместо %H:%00)
            vol_r = row['volume'] / baseline['vol_median'] if baseline['vol_median'] > 0 else 1.0
            p_ch = row['price_change_pct']
            oi_ch = row['oi_change_pct']
            tag = self.classify_candle_status(p_ch, oi_ch, vol_r)
            
            context_lines.append(
                f"[{c_time}] Price: {row['close']} ({p_ch:+.2f}%) | "
                f"dOI: {oi_ch:+.2f}% | Vol: {row['volume']:.0f} ({vol_r:.2f}x Med) | Tag: {tag}"
            )

        # Сводка закрывшегося часа
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

        # Анализ текущей лайв-свечи
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

        projected_vol_ratio = projected_volume / baseline['vol_median'] if baseline['vol_median'] > 0 else 1.0
        live_status = self.classify_candle_status(live_price_pct, live_oi_pct, projected_vol_ratio)

        # Динамика OI в минуту
        speed_oi = live_oi_pct / minutes_passed

        # Доля покупателей (Taker Buy)
        taker_buy_pct = (live_candle['buy_volume'] / vol_current * 100) if vol_current > 0 else 50.0

        is_volume_anomalous = projected_volume >= (baseline['vol_median'] * 1.5)
        is_oi_anomalous = abs(live_oi_pct) >= (baseline['abs_oi_median'] * 2.0)

        signal_code = "NO_SIGNAL"
        if is_volume_anomalous and is_oi_anomalous:
            signal_code = live_status

        return {
            "candle_open_str": candle_open_time.strftime("%Y-%m-%d %H:00"),
            "timestamp_now": now_time.strftime("%H:%M"),
            "minutes_passed": minutes_passed,
            "price": live_candle['close'],
            "live_price_pct": round(live_price_pct, 2),
            "live_oi_pct": round(live_oi_pct, 2),
            "speed_oi": round(speed_oi, 4),
            "vol_projected_ratio": round(projected_vol_ratio, 2),
            "taker_buy_pct": round(taker_buy_pct, 1),
            "live_status": live_status,
            "signal_code": signal_code,
            "closed_hour_summary": closed_hour_summary,
            "context_lines": context_lines
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
    print(f" Starting Binance Futures Scanner {scanner.symbol} | Intra-day Trend Mode")
    print("=" * 90)

    last_signal_key = None
    current_active_hour = None

    while True:
        try:
            data = scanner.analyze_live_market()

            # Вывод блока 3H контекста
            print("--- LAST 3 HOURS CONTEXT ---")
            for line in data['context_lines']:
                print(line)
            print("-" * 90)
            print("Monitoring market state (interval: 10m)...\n")

            # Вывод сводки при наступлении нового часа
            if current_active_hour is not None and data['candle_open_str'] != current_active_hour:
                print(f"\n{data['closed_hour_summary']}\n")
                logging.info(data['closed_hour_summary'])

            current_active_hour = data['candle_open_str']

            # Вывод текущего состояния
            status_suffix = f" | Status: {data['live_status']}" if data['signal_code'] != "NO_SIGNAL" else ""

            console_output = (
                f"[{data['timestamp_now']} | {data['minutes_passed']}m/60m] "
                f"BTC: {data['price']} ({data['live_price_pct']:+.2f}%) | "
                f"dOI: {data['live_oi_pct']:+.2f}% (Spd: {data['speed_oi']:+.4f}%/m) | "
                f"Vol: {data['vol_projected_ratio']}x | "
                f"TakerBuy: {data['taker_buy_pct']}%"
                f"{status_suffix}"
            )
            print(console_output)

            # Логирование аномалий
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

        # Пауза 10 минут (600 секунд)
        time.sleep(600)