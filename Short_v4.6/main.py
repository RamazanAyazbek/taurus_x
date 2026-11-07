import config
from log_parser import parse_taurus_log
from backtester import TaurusShortBacktester
from reporter import export_analysis


def main():
    print("[1] Чтение Taurus log только для поиска сигналов SHORT...")
    df = parse_taurus_log(config.LOG_FILE)
    print(f"[+] Записей мониторинга: {len(df)}")
    if df.empty:
        raise SystemExit("Не удалось извлечь decision records из указанного лог-файла.")

    print("[2] SHORT: сигналы + Binance Futures 1m...")
    tester = TaurusShortBacktester(config)
    tester.run(df)
    export_analysis(tester.trades, config, tester.s1_rejections, tester.filter_counts)


if __name__ == "__main__":
    main()
