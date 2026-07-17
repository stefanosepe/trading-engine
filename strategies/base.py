"""
Pattern Strategy: ogni strategia concreta implementa questa interfaccia.
Il motore (engine) non sa nulla dei dettagli di una strategia specifica,
sa solo che riceve MarketEvent e produce (eventualmente) SignalEvent.

REGOLA D'ORO: una Strategy deve essere una funzione pura rispetto ai dati
che riceve. Non deve avere accesso diretto al broker, al portfolio o
"sapere" se sta girando in backtest o in live. Questo è ciò che garantisce
che il comportamento sia identico in tutte le fasi.
"""
from abc import ABC, abstractmethod
from collections import deque

from core.events import MarketEvent, SignalEvent


class Strategy(ABC):
    """Interfaccia base per tutte le strategie."""

    @abstractmethod
    def on_market_event(self, event: MarketEvent) -> SignalEvent | None:
        """
        Chiamato dal motore ad ogni nuova barra di mercato.
        Ritorna un SignalEvent se la strategia genera un segnale,
        altrimenti None.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Reset dello stato interno (utile tra un backtest e l'altro)."""
        pass


class RollingWindowStrategy(Strategy):
    """
    Classe di comodo per strategie che hanno bisogno di una finestra
    mobile di N barre per calcolare i propri indicatori (es. medie mobili).
    """

    def __init__(self, window_size: int):
        self.window_size = window_size
        self._history: dict[str, deque] = {}

    def _push(self, symbol: str, event: MarketEvent) -> deque:
        if symbol not in self._history:
            self._history[symbol] = deque(maxlen=self.window_size)
        self._history[symbol].append(event.close)
        return self._history[symbol]

    def reset(self) -> None:
        self._history.clear()
