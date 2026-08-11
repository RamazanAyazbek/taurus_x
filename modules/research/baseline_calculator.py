import json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta


class BaselineCalculator:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        history_days: int = 30,
        timezone_offset: int = 5,
        output_json: str = "baseline_metrics.json"
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.history_days = history_days
        self.history_limit = min(history_days * 24, 1000)
        self.timezone_offset = timezone_offset
        self.output_json = output_json
        self.base_url = "https://fapi.binance.com"

    def fetch_historical_data(self) -> pd.DataFrame:
        """Загружает свечи и OI за 30 дней и объединяет их."""
        offset_hours = timedelta(hours=self.timezone_offset)
        tz_info = timezone(offset_hours)

        # 1. Загрузка свечей (Klines)
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params_klines = {
            "symbol": self.symbol,
            "interval": self.timeframe,
            "limit": self.history_limit
        }
        res_klines = requests.get(klines_url, params=params_klines).json()

        df_klines = pd.DataFrame(res_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
        df_klines[cols] = df_klines[cols].astype(float)

        df_klines['time'] = (
            pd.to_datetime(df_klines['open_time'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 2. Загрузка истории Открытого Интереса (OI)
        oi_url = f"{self.base_url}/futures/data/openInterestHist"
        params_oi = {
            "symbol": self.symbol,
            "period": self.timeframe,
            "limit": self.history_limit
        }
        res_oi = requests.get(oi_url, params=params_oi).json()

        df_oi = pd.DataFrame(res_oi)
        df_oi['sumOpenInterest'] = df_oi['sumOpenInterest'].astype(float)
        df_oi['time'] = (
            pd.to_datetime(df_oi['timestamp'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 3. Объединение свечей и OI
        df = pd.merge_asof(
            df_klines.sort_values('time'),
            df_oi[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi'})

        # Процентные изменения
        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100

        # Исключаем текущую не зафиксированную свечу
        return df.iloc[:-1].copy()

    def filter_out_weekends(self, df: pd.DataFrame) -> pd.DataFrame:
        """Исключает субботу (5) и воскресенье (6)."""
        return df[~df['time'].dt.dayofweek.isin([5, 6])].copy()

    def calculate_and_save(self) -> dict:
        """Считaет статистику, сохраняет JSON и выводит короткий отчет."""
        df_raw = self.fetch_historical_data()
        df_workdays = self.filter_out_weekends(df_raw)

        # Определение точного временного периода выборки
        start_date = df_workdays['time'].min().strftime("%Y-%m-%d %H:%M")
        end_date = df_workdays['time'].max().strftime("%Y-%m-%d %H:%M")

        abs_oi_change = df_workdays['oi_change_pct'].abs()
        abs_price_change = df_workdays['price_change_pct'].abs()

        metrics = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period_start": start_date,
            "period_end": end_date,
            "history_days_total": self.history_days,
            "workday_candles_analyzed": len(df_workdays),
            "volume": {
                "mean": round(float(df_workdays['volume'].mean()), 1),
                "median": round(float(df_workdays['volume'].median()), 1),
                "std": round(float(df_workdays['volume'].std()), 1)
            },
            "abs_doi": {
                "mean": round(float(abs_oi_change.mean()), 3),
                "median": round(float(abs_oi_change.median()), 3),
                "std": round(float(abs_oi_change.std()), 3)
            },
            "abs_dprice": {
                "mean": round(float(abs_price_change.mean()), 3),
                "median": round(float(abs_price_change.median()), 3),
                "std": round(float(abs_price_change.std()), 3)
            }
        }

        # Запись только в JSON-файл
        with open(self.output_json, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=4)

        start_date = df_workdays['time'].min().strftime("%Y-%m-%d")
        end_date = df_workdays['time'].max().strftime("%Y-%m-%d")
        # Вывод в консоль ровно один раз
        print("=" * 80)
        # print(f"✅ Baseline saved to '{self.output_json}'")
        print(f"Period: {start_date} -> {end_date}")
        print(f"Volume Median: {metrics['volume']['median']} | dOI Median: {metrics['abs_doi']['median']}% | dPrice Median: {metrics['abs_dprice']['median']}%")
        # print("=" * 80)

        return metrics


if __name__ == "__main__":
    calculator = BaselineCalculator(
        symbol="BTCUSDT",
        timeframe="1h",
        history_days=30,
        timezone_offset=5,
        output_json="baseline_metrics.json"
    )
    calculator.calculate_and_save()