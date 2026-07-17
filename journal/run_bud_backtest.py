"""
Test della strategia BUD su dati storici reali BTCUSDT (1h, Binance,
~5-6 mesi, scaricati da un dataset pubblico su GitHub).

Uso:
    python -m journal.run_bud_backtest
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedRiskPerTradeManager
from strategies.bud_strategy import BUDStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    data_path = Path(__file__).resolve().parent.parent / "data" / "btcusdt_1h.csv"
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} non trovato")

    feed = CSVDataFeed(filepath=str(data_path), symbol="BTC/USDT")
    strategy = BUDStrategy(
        ema_fast_period=5,
        ema_stop_period=10,
        bud_lookback_min=3,
        bud_expansion_mult=1.5,
        appoggio_min_candles=1,
        appoggio_max_candles=6,
        innesco_contraction_ratio=0.5,
        atr_period=14,
        stop_buffer_atr_mult=0.25,
        tp_r_multiple=2.0,
    )
    risk_manager = FixedRiskPerTradeManager(risk_per_trade=10.0, tp_r_multiple=2.0)
    broker = PaperJournalBroker(initial_capital=1000.0)

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
    )
    engine.run()

    print("\n=== Statistiche BUD su BTC/USDT (1h) ===")
    for k, v in broker.stats().items():
        print(f"{k}: {v}")

    import csv
    out_path = Path(__file__).resolve().parent.parent / "bud_trades.csv"
    trades = broker.trade_log()
    if trades:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\nLog trade salvato in {out_path}")
    else:
        print("\nNessun trade generato: probabile che i parametri siano troppo restrittivi "
              "per i dati usati, o che il pattern non si presenti (spesso) su BTC/USDT 1h.")


if __name__ == "__main__":
    main()
