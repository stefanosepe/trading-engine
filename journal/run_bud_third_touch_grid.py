"""
Grid search su BTC: timeframe x filtro trend x prossimita' del terzo tocco.

Uso:
    python -m journal.run_bud_third_touch_grid
"""
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedRiskPerTradeManager
from strategies.bud_bidirectional import BUDBidirectionalStrategy

TIMEFRAMES = {
    "1h": "btcusdt_1h_full.csv",
    "4h": "btcusdt_4h.csv",
    "1d": "btcusdt_1d.csv",
}

TREND_OPTIONS = {"trend_on": 60, "trend_off": None}

PROXIMITY_LEVELS = {
    "stretto": dict(tolerance_pct=0.005, approach_pct=0.01, lookback_bars=20),
    "medio":   dict(tolerance_pct=0.01,  approach_pct=0.02, lookback_bars=40),
    "largo":   dict(tolerance_pct=0.02,  approach_pct=0.04, lookback_bars=80),
}


def run_one(data_path, ema_trend_period, proximity_kwargs):
    feed = CSVDataFeed(filepath=str(data_path), symbol="BTC/USDT")
    strategy = BUDBidirectionalStrategy(
        ema_fast_period=5,
        ema_stop_period=10,
        ema_trend_period=ema_trend_period,
        bud_lookback_min=3,
        bud_expansion_mult=1.5,
        appoggio_min_candles=1,
        appoggio_max_candles=6,
        innesco_contraction_ratio=0.5,
        atr_period=14,
        stop_buffer_atr_mult=0.25,
        tp_r_multiple=2.0,
        require_third_touch=True,
        third_touch_pivot_lookback=3,
        third_touch_tolerance_pct=proximity_kwargs["tolerance_pct"],
        third_touch_approach_pct=proximity_kwargs["approach_pct"],
        third_touch_lookback_bars=proximity_kwargs["lookback_bars"],
    )
    risk_manager = FixedRiskPerTradeManager(risk_per_trade=10.0, tp_r_multiple=2.0)
    broker = PaperJournalBroker(initial_capital=1000.0)
    engine = Engine(feed, strategy, risk_manager, broker)
    engine.run()

    trades = broker.trade_log()
    long_trades = [t for t in trades if t["direction"] == "BUY"]
    short_trades = [t for t in trades if t["direction"] == "SELL"]

    def wr(subset):
        return round(sum(1 for t in subset if t["won"]) / len(subset) * 100, 1) if subset else None

    return {
        "n_trades": len(trades),
        "win_rate_pct": wr(trades),
        "pnl_R": sum(t["pnl"] for t in trades) / 10.0 if trades else 0.0,
        "n_long": len(long_trades),
        "n_short": len(short_trades),
        "long_wr_pct": wr(long_trades),
        "short_wr_pct": wr(short_trades),
    }


def main():
    data_dir = Path(__file__).resolve().parent.parent / "data"
    results = []

    for tf_label, filename in TIMEFRAMES.items():
        data_path = data_dir / filename
        if not data_path.exists():
            print(f"SKIP {tf_label}: {data_path} non trovato")
            continue

        for trend_label, ema_trend_period in TREND_OPTIONS.items():
            for prox_label, prox_kwargs in PROXIMITY_LEVELS.items():
                stats = run_one(data_path, ema_trend_period, prox_kwargs)
                row = {"timeframe": tf_label, "trend": trend_label, "prossimita": prox_label, **stats}
                results.append(row)
                print(
                    f"{tf_label:>3} | {trend_label:>9} | {prox_label:>7} | "
                    f"trade={row['n_trades']:>4} | wr={str(row['win_rate_pct']):>6} | "
                    f"pnl={row['pnl_R']:>6}R | long={row['n_long']}({row['long_wr_pct']}) | "
                    f"short={row['n_short']}({row['short_wr_pct']})"
                )

    out_path = Path(__file__).resolve().parent.parent / "bud_third_touch_grid.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nRisultati completi salvati in {out_path}")


if __name__ == "__main__":
    main()
