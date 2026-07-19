"""
Interfaccia Broker: astrae "dove viene eseguito l'ordine".
E' l'astrazione chiave che permette a backtest/paper/live di condividere
lo stesso engine: cambia solo l'implementazione di questa classe.
"""
from abc import ABC, abstractmethod

from core.events import FillEvent, OrderEvent


class Broker(ABC):
    @abstractmethod
    def execute_order(self, order: OrderEvent) -> FillEvent:
        """Esegue l'ordine e ritorna il FillEvent risultante."""
        raise NotImplementedError

    @abstractmethod
    def get_equity(self) -> float:
        """Equity corrente (cash + valore posizioni)."""
        raise NotImplementedError

    def check_pending(self, market_event) -> list:
        """
        Hook opzionale chiamato dall'engine ad ogni MarketEvent, PRIMA di
        valutare nuovi segnali. Usato dai broker che tengono trade "aperti"
        in attesa che TP/SL vengano toccati (es. PaperJournalBroker).
        Il broker di backtest/live standard non lo implementa (default: []).
        Ritorna la lista di eventuali FillEvent generati dalla chiusura
        di trade pendenti.
        """
        return []

    def has_open_position(self, symbol: str, source: str | None = None) -> bool:
        """
        Hook opzionale: True se il broker ha gia' una posizione/trade
        aperto su questo simbolo (per questa specifica strategia, se piu'
        strategie girano in parallelo — vedi `source` in SignalEvent).
        L'Engine lo usa per evitare di aprire un secondo trade mentre il
        primo e' ancora in corso. Default False (comportamento invariato
        per i broker che non lo gestiscono).
        """
        return False
