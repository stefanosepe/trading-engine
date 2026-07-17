"""
DataFeed astrae "da dove arrivano le barre di mercato".
In backtest e' un iteratore su dati storici. In paper/live e' un
generatore che aspetta la chiusura di ogni nuova barra sull'exchange.
"""
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator

import pandas as pd

from core.events import MarketEvent


class DataFeed(ABC):
    @abstractmethod
    def __iter__(self) -> Iterator[MarketEvent]:
        raise NotImplementedError


class CSVDataFeed(DataFeed):
    """
    Legge un CSV con colonne: timestamp, open, high, low, close, volume.
    Usato per il backtest.
    """

    def __init__(self, filepath: str, symbol: str):
        self.filepath = filepath
        self.symbol = symbol

    def __iter__(self) -> Iterator[MarketEvent]:
        df = pd.read_csv(self.filepath, parse_dates=["timestamp"])
        df = df.sort_values("timestamp")
        for row in df.itertuples(index=False):
            yield MarketEvent(
                symbol=self.symbol,
                timestamp=row.timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )


class CCXTLiveDataFeed(DataFeed):
    """
    Feed live/paper: interroga periodicamente l'exchange (via ccxt) per
    l'ultima candela chiusa sul timeframe scelto, ed emette un
    MarketEvent solo quando arriva una candela nuova.

    Nota implementativa: qui uso polling REST per semplicita' e
    robustezza (meno codice, riconnessioni piu' semplici). Per
    intraday molto rapido converrebbe passare a websocket, ma per
    partire il polling e' piu' che sufficiente ed e' molto piu'
    facile da debuggare.
    """

    _TIMEFRAME_SECONDS = {
        "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
    }

    def __init__(
        self,
        exchange,  # istanza ccxt gia' configurata (puo' essere condivisa col broker)
        symbol: str,
        timeframe: str = "1h",
        poll_interval_sec: int = 15,
    ):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.poll_interval_sec = poll_interval_sec
        self._last_candle_ts = None

    def __iter__(self) -> Iterator[MarketEvent]:
        while True:
            candles = self.exchange.fetch_ohlcv(
                self.symbol, timeframe=self.timeframe, limit=2
            )
            if len(candles) >= 2:
                # prendo la penultima: e' l'ultima candela CHIUSA
                # (l'ultima e' ancora in formazione)
                ts, o, h, l, c, v = candles[-2]
                if ts != self._last_candle_ts:
                    self._last_candle_ts = ts
                    yield MarketEvent(
                        symbol=self.symbol,
                        timestamp=pd.to_datetime(ts, unit="ms"),
                        open=o, high=h, low=l, close=c, volume=v,
                    )
            time.sleep(self.poll_interval_sec)
