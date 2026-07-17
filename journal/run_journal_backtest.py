"""
Journal in backtest: stessa idea del papertrading su TP/SL, ma su dati
storici, cosi' hai un'idea del win rate prima ancora di lasciarlo girare
in tempo reale.

Uso:
    python -m journal.run_journal_backtest
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedFractionalRiskManager
from strategies.ema_cross import EMACrossStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    data_path = Path(__file__).resolve().parent.parent / "data" / "sample_ohlcv.csv"
    if not data_path.exists():
        raise FileNotFoundError(
            f"{data_path} non trovato. Genera i dati con: "
            "python -m data.generate_sample_data"
        )

    feed = CSVDataFeed(filepath=str(data_path), symbol="SYNTH/USD")
    # allow_short=True: la strategia genera solo LONG/SHORT, mai EXIT.
    # La chiusura del trade e' SEMPRE gestita dal TP/SL del journal broker.
    strategy = EMACrossStrategy(fast_period=12, slow_period=26, allow_short=True)
    risk_manager = FixedFractionalRiskManager(fraction=0.95, sl_pct=0.02, tp_pct=0.04)
    broker = PaperJournalBroker()

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
    )
    engine.run()

    print("\n=== Statistiche journal ===")
    for k, v in broker.stats().items():
        print(f"{k}: {v}")

    import csv
    out_path = Path(__file__).resolve().parent.parent / "journal_trades.csv"
    trades = broker.trade_log()
    if trades:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\nLog dei trade salvato in {out_path}")


if __name__ == "__main__":
    main()
