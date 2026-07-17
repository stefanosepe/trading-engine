"""
BUDBidirectionalStrategy: fa girare LO STESSO identico rilevatore BUD sia
per il lato long che per il lato short, ribaltando verticalmente i dati
per lo short (open'=-open, high'=-low, low'=-high, close'=-close) invece
di duplicare/invertire la logica a mano.

Questo garantisce che long e short siano PERFETTAMENTE speculari per
costruzione: non possono divergere per un bug di copia-incolla, perche'
la logica di rilevamento vive in un solo posto (BUDStrategy).
"""
from core.events import MarketEvent, SignalEvent, SignalType
from strategies.base import Strategy
from strategies.bud_strategy import BUDStrategy


class BUDBidirectionalStrategy(Strategy):
    def __init__(self, **bud_kwargs):
        # due istanze indipendenti (stato separato), stessi parametri
        self._long = BUDStrategy(**bud_kwargs)
        self._short = BUDStrategy(**bud_kwargs)

    def reset(self) -> None:
        self._long.reset()
        self._short.reset()

    def on_market_event(self, event: MarketEvent) -> SignalEvent | None:
        long_signal = self._long.on_market_event(event)

        mirrored_event = self._mirror_market_event(event)
        short_signal_mirrored = self._short.on_market_event(mirrored_event)

        if long_signal is not None:
            return long_signal
        if short_signal_mirrored is not None:
            return self._unmirror_signal(short_signal_mirrored)
        return None

    @staticmethod
    def _mirror_market_event(event: MarketEvent) -> MarketEvent:
        return MarketEvent(
            symbol=event.symbol,
            timestamp=event.timestamp,
            open=-event.open,
            high=-event.low,
            low=-event.high,
            close=-event.close,
            volume=event.volume,
        )

    @staticmethod
    def _unmirror_signal(signal: SignalEvent) -> SignalEvent:
        # il rilevatore "long" su dati ribaltati ha trovato un setup:
        # nello spazio reale e' uno SHORT. Si ribaltano i livelli di prezzo.
        return SignalEvent(
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            signal_type=SignalType.SHORT,
            stop_price=-signal.stop_price if signal.stop_price is not None else None,
            take_profit_price=(
                -signal.take_profit_price if signal.take_profit_price is not None else None
            ),
        )
