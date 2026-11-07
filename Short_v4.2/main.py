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

    print("[2] Один запуск симулятора: Binance Futures 1m TP/SL/TIMEOUT...")
    tester = TaurusShortBacktester(config)
    tester.run(df)
    export_analysis(tester.trades, config)


if __name__ == "__main__":
    main()
