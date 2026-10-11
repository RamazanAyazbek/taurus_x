import config
from backtester import TaurusRealisticStrictBacktester
from log_parser import parse_taurus_log
from oi_features import add_prev_hour_oi_features
from reporter import export_analysis


def main():
    log_file = config.LOG_FILE

    try:
        print("[1] Парсинг сигналов из лог-файла...")
        df_logs = parse_taurus_log(log_file)
        print(f"[+] Считано строк: {len(df_logs)}")

        if config.ENABLE_OI_FEATURES:
            df_logs = add_prev_hour_oi_features(df_logs)

        print("[2] Запуск бэктеста...")

        tester = TaurusRealisticStrictBacktester(config)
        tester.run(df_logs, config.SYMBOL)
        export_analysis(tester.trades, config.OUTPUT_CSV)

    except FileNotFoundError:
        print(f"Файл {log_file} не найден.")


if __name__ == "__main__":
    main()
