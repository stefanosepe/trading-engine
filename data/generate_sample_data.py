"""
Genera un CSV di dati OHLCV sintetici (random walk con drift) solo per
avere subito qualcosa su cui far girare il backtest end-to-end.
Da sostituire con dati storici reali (es. scaricati via ccxt.fetch_ohlcv)
appena si vuole un backtest che dica qualcosa di vero.
"""
import numpy as np
import pandas as pd


def generate(
    n_bars: int = 500,
    start_price: float = 100.0,
    drift: float = 0.0003,
    volatility: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=drift, scale=volatility, size=n_bars)
    close = start_price * np.cumprod(1 + returns)

    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n_bars))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n_bars))
    volume = rng.uniform(1000, 5000, n_bars)

    timestamps = pd.date_range("2023-01-01", periods=n_bars, freq="D")

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


if __name__ == "__main__":
    df = generate()
    df.to_csv("data/sample_ohlcv.csv", index=False)
    print(f"Generato data/sample_ohlcv.csv con {len(df)} barre")
