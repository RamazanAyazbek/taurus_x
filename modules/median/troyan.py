import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class BinanceFuturesTrendAnalyzer:
    def __init__(
            self,
            symbol: str = "BTCUSDT",
            timeframe: str = "1h",
            vol_sma_period: int = 24,
            vol_threshold: float = 1.35,
            oi_threshold_pct: float = 0.8,
            price_threshold_pct: float = 0.3,
            timezone_offset: int = 5  # GMT+5 (Твой часовой пояс)
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.vol_sma_period = vol_sma_period
        self.vol_threshold = vol_threshold
        self.oi_threshold_pct = oi_threshold_pct
        self.price_threshold_pct = price_threshold_pct
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"

    def fetch_historical_data(self, hours_back: int = 300) -> pd.DataFrame:
        """
        Загружает данные за последние N часов.
        Максимум Binance за 1 запрос = 500 свечей.
        """
        limit = min(hours_back, 500)  # Ограничение API Binance

        # 1. Загрузка свечей
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": limit}
        res_klines = requests.get(klines_url, params=params).json()

        df_klines = pd.DataFrame(res_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
        df_klines[cols] = df_klines[cols].astype(float)

        # КОНВЕРТАЦИЯ В GMT+5
        df_klines['time'] = (
            pd.to_datetime(df_klines['open_time'], unit='ms')
            .dt.tz_localize('UTC')
            .dt.tz_convert(
                f'Etc/GMT{-self.timezone_offset if self.timezone_offset >= 0 else f"+{abs(self.timezone_offset)}"}')
            .dt.tz_localize(None)  # Убираем маркер таймзоны для чистоты вывода
        )

        # 2. Загрузка Открытого Интереса
        oi_url = f"{self.base_url}/futures/data/openInterestHist"
        params_oi = {"symbol": self.symbol, "period": self.timeframe, "limit": limit}
        # res_oi = requests.get(oi_url, params_oi=params_oi).json()
        res_oi = requests.get(oi_url, params=params_oi).json()

        df_oi = pd.DataFrame(res_oi)
        df_oi['sumOpenInterest'] = df_oi['sumOpenInterest'].astype(float)

        # КОНВЕРТАЦИЯ В GMT+5
        df_oi['time'] = (
            pd.to_datetime(df_oi['timestamp'], unit='ms')
            .dt.tz_localize('UTC')
            .dt.tz_convert(
                f'Etc/GMT{-self.timezone_offset if self.timezone_offset >= 0 else f"+{abs(self.timezone_offset)}"}')
            .dt.tz_localize(None)
        )

        # 3. Синхронизация
        df = pd.merge_asof(
            df_klines.sort_values('time'),
            df_oi[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi', 'taker_buy_volume': 'buy_volume'})

        df['sell_volume'] = df['volume'] - df['buy_volume']
        return df[['time', 'open', 'high', 'low', 'close', 'volume', 'buy_volume', 'sell_volume', 'oi']]

    def evaluate_trend_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100
        df['vol_sma'] = df['volume'].rolling(window=self.vol_sma_period).mean()
        df['vol_ratio'] = np.where(df['vol_sma'] > 0, df['volume'] / df['vol_sma'], 1.0)

        def classify_candle(row):
            price_pct = row['price_change_pct']
            oi_pct = row['oi_change_pct']
            vol_ratio = row['vol_ratio']

            if pd.isna(price_pct) or pd.isna(oi_pct) or pd.isna(vol_ratio):
                return "WARMUP"

            has_vol = vol_ratio >= self.vol_threshold
            has_oi = abs(oi_pct) >= self.oi_threshold_pct
            has_price = abs(price_pct) >= self.price_threshold_pct

            if not (has_vol and has_oi and has_price):
                return "NO_SIGNAL"

            if price_pct > 0:
                return "🟢 СИЛЬНЫЙ БЫЧИЙ ТРЕНД (Новые Лонги)" if oi_pct > 0 else "⚡ ШОРТ-СКВИЗ (Вынос Шортов)"
            else:
                return "🔴 СИЛЬНЫЙ МЕДВЕЖИЙ ТРЕНД (Новые Шорты)" if oi_pct > 0 else "💥 КАПИТУЛЯЦИЯ (Промывка Лонгов)"

        df['trend_signal'] = df.apply(classify_candle, axis=1)
        return df


# ==========================================
# УДОБНЫЙ ЗАПУСК С ПАРАМЕТРАМИ
# ==========================================
if __name__ == "__main__":

    # ⚙️ НАСТРОЙКИ АНАЛИЗА
    DAYS_TO_ANALYZE = 10  # За сколько дней назад качать данные (например, 10 дней)
    TIMEZONE = 5  # Твой часовой пояс (GMT+5)

    HOURS_BACK = DAYS_TO_ANALYZE * 24

    analyzer = BinanceFuturesTrendAnalyzer(
        symbol="BTCUSDT",
        timeframe="1h",
        vol_sma_period=24,  # 24 часа для SMA
        vol_threshold=1.35,  # Объем +35%
        oi_threshold_pct=0.8,  # OI >= 0.8%
        price_threshold_pct=0.3,  # Price >= 0.3%
        timezone_offset=TIMEZONE
    )

    df_raw = analyzer.fetch_historical_data(hours_back=HOURS_BACK)
    df_result = analyzer.evaluate_trend_signals(df_raw)

    start_date = df_result['time'].min().strftime('%Y-%m-%d %H:%M')
    end_date = df_result['time'].max().strftime('%Y-%m-%d %H:%M')

    print(f"\nАнализ рынка с {start_date} по {end_date} (Время GMT+{TIMEZONE})")

    signals = df_result[~df_result['trend_signal'].isin(["WARMUP", "NO_SIGNAL"])]

    print("=" * 95)
    print(f"НАЙДЕНЫ СИГНАЛЫ (Всего: {len(signals)} из {len(df_result)} свечей)")
    print("=" * 95)

    for idx, row in signals.iterrows():
        t_str = row['time'].strftime('%Y-%m-%d %H:%M')
        print(f"[{t_str}] Price: {row['close']:.1f} ({row['price_change_pct']:+.2f}%) | "
              f"ΔOI: {row['oi_change_pct']:+.2f}% | Vol: {row['vol_ratio']:.2f}x | "
              f"Сигнал: {row['trend_signal']}")