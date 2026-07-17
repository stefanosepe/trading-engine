"""
Entry point per il backtest.

Uso:
    python -m backtest.run_backtest
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.backtest_broker import BacktestBroker
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
    strategy = EMACrossStrategy(fast_period=12, slow_period=26, allow_short=False)
    risk_manager = FixedFractionalRiskManager(fraction=0.95)
    broker = BacktestBroker(initial_capital=10_000.0, commission_pct=0.001, slippage_pct=0.0005)

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
    )

    portfolio = engine.run()

    stats = portfolio.summary_stats()
    print("\n=== Risultati backtest ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    out_path = Path(__file__).resolve().parent.parent / "backtest_equity_curve.csv"
    portfolio.to_dataframe().to_csv(out_path)
    print(f"\nEquity curve salvata in {out_path}")


if __name__ == "__main__":
    main()
