"""
Portfolio: registra l'equity nel tempo e i fill ricevuti.
Usato sia per calcolare le metriche di backtest (Sharpe, drawdown, ecc.)
sia per il monitoraggio a runtime durante paper/live.
"""
from dataclasses import dataclass, field

from core.events import FillEvent


@dataclass
class Portfolio:
    equity_curve: list[tuple] = field(default_factory=list)  # (timestamp, equity)
    fills: list[FillEvent] = field(default_factory=list)

    def record_fill(self, fill: FillEvent) -> None:
        self.fills.append(fill)

    def record_equity(self, timestamp, equity: float) -> None:
        self.equity_curve.append((timestamp, equity))

    def to_dataframe(self):
        import pandas as pd
        df = pd.DataFrame(self.equity_curve, columns=["timestamp", "equity"])
        return df.set_index("timestamp")

    def summary_stats(self) -> dict:
        import numpy as np

        df = self.to_dataframe()
        if len(df) < 2:
            return {"n_trades": len(self.fills)}

        returns = df["equity"].pct_change().dropna()
        total_return = df["equity"].iloc[-1] / df["equity"].iloc[0] - 1

        running_max = df["equity"].cummax()
        drawdown = (df["equity"] - running_max) / running_max
        max_drawdown = drawdown.min()

        sharpe = 0.0
        if returns.std() > 0:
            # annualizzazione approssimata assumendo barre giornaliere;
            # da adattare al timeframe reale usato
            sharpe = (returns.mean() / returns.std()) * (252 ** 0.5)

        return {
            "n_trades": len(self.fills),
            "total_return_pct": round(total_return * 100, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_approx": round(sharpe, 2),
            "final_equity": round(df["equity"].iloc[-1], 2),
        }
