"""
PaperJournalBroker: il "papertrading su carta vera" che avevi chiesto.

Non si connette a nessun broker reale. Quando riceve un OrderEvent con
stop_loss/take_profit, apre un trade virtuale e lo tiene in sospeso.
Ad ogni nuova barra di mercato (via check_pending, chiamato dall'Engine)
controlla se il prezzo ha toccato TP o SL usando high/low della barra, e
se si' chiude il trade registrando l'esito.

Alla fine espone le statistiche che interessano a te: quanti trade,
percentuale di successo (win rate), R medio ottenuto.

LIMITE IMPORTANTE da tenere a mente: se in una singola barra vengono
toccati SIA il TP che lo SL (barra molto volatile), non possiamo sapere
con certezza quale sia stato colpito per primo solo da OHLC. Questo
broker adotta l'ipotesi conservativa: assume che lo SL sia stato toccato
per primo (worst case). Su timeframe piu' bassi (es. 1m) il problema si
riduce parecchio. Se serve precisione assoluta, l'alternativa e' usare
un feed di dati tick-by-tick invece che a barre.
"""
from dataclasses import dataclass, field

from core.events import FillEvent, OrderDirection, OrderEvent
from broker.base import Broker


@dataclass
class _OpenTrade:
    symbol: str
    direction: OrderDirection
    quantity: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: object


class PaperJournalBroker(Broker):
    def __init__(self, initial_capital: float = 10_000.0):
        # capitale puramente virtuale: serve solo come base per il position
        # sizing (es. "rischia il 2% di 10k"), non rappresenta soldi reali
        self.initial_capital = initial_capital
        self._open_trades: dict[str, _OpenTrade] = {}  # 1 trade aperto per simbolo
        self._closed_trades: list[dict] = []
        self._last_price: dict[str, float] = {}

    def update_market_price(self, symbol: str, price: float) -> None:
        self._last_price[symbol] = price

    def execute_order(self, order: OrderEvent) -> FillEvent:
        entry_price = self._last_price.get(order.symbol, order.limit_price)
        if entry_price is None:
            raise RuntimeError(f"Nessun prezzo disponibile per {order.symbol}")

        self._open_trades[order.symbol] = _OpenTrade(
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.quantity,
            entry_price=entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=order.timestamp,
        )

        # fill "informativo": conferma l'apertura, non e' un'esecuzione reale
        return FillEvent(
            symbol=order.symbol,
            timestamp=order.timestamp,
            direction=order.direction,
            quantity=order.quantity,
            fill_price=entry_price,
            commission=0.0,
        )

    def check_pending(self, market_event) -> list[FillEvent]:
        symbol = market_event.symbol
        trade = self._open_trades.get(symbol)
        if trade is None:
            return []

        high, low = market_event.high, market_event.low
        hit_sl = trade.stop_loss is not None and (
            (trade.direction == OrderDirection.BUY and low <= trade.stop_loss)
            or (trade.direction == OrderDirection.SELL and high >= trade.stop_loss)
        )
        hit_tp = trade.take_profit is not None and (
            (trade.direction == OrderDirection.BUY and high >= trade.take_profit)
            or (trade.direction == OrderDirection.SELL and low <= trade.take_profit)
        )

        if not hit_sl and not hit_tp:
            return []

        # ipotesi conservativa se toccati entrambi nella stessa barra: vince lo SL
        outcome = "SL" if hit_sl else "TP"
        exit_price = trade.stop_loss if hit_sl else trade.take_profit

        pnl_per_unit = (
            exit_price - trade.entry_price
            if trade.direction == OrderDirection.BUY
            else trade.entry_price - exit_price
        )
        pnl = pnl_per_unit * trade.quantity
        won = pnl > 0

        self._closed_trades.append(
            {
                "symbol": symbol,
                "direction": trade.direction.value,
                "entry_price": trade.entry_price,
                "exit_price": exit_price,
                "outcome": outcome,
                "pnl": pnl,
                "won": won,
                "opened_at": trade.opened_at,
                "closed_at": market_event.timestamp,
            }
        )
        del self._open_trades[symbol]

        exit_direction = (
            OrderDirection.SELL if trade.direction == OrderDirection.BUY else OrderDirection.BUY
        )
        return [
            FillEvent(
                symbol=symbol,
                timestamp=market_event.timestamp,
                direction=exit_direction,
                quantity=trade.quantity,
                fill_price=exit_price,
                commission=0.0,
            )
        ]

    def get_equity(self) -> float:
        # equity virtuale: capitale iniziale + PnL chiusi (non e' un vero conto)
        return self.initial_capital + sum(t["pnl"] for t in self._closed_trades)

    def has_open_position(self, symbol: str) -> bool:
        return symbol in self._open_trades

    def stats(self) -> dict:
        n = len(self._closed_trades)
        if n == 0:
            return {"n_trades": 0, "win_rate_pct": None, "open_trades": len(self._open_trades)}

        wins = sum(1 for t in self._closed_trades if t["won"])
        total_pnl = sum(t["pnl"] for t in self._closed_trades)
        avg_win = (
            sum(t["pnl"] for t in self._closed_trades if t["won"]) / wins if wins else 0.0
        )
        losses = n - wins
        avg_loss = (
            sum(t["pnl"] for t in self._closed_trades if not t["won"]) / losses
            if losses
            else 0.0
        )

        return {
            "n_trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / n * 100, 2),
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "open_trades": len(self._open_trades),
        }

    def trade_log(self) -> list[dict]:
        return list(self._closed_trades)
