"""
Telegram notifications - alerts for your automations (flows, scheduler,
failures). Zero dependencies (stdlib urllib). Fully optional: if
TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are missing from the environment,
everything silently no-ops. Send failures never break the caller.
"""

import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


def _send(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat or ":" not in token:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
        return True
    except Exception as e:
        logger.debug(f"telegram send failed: {e}")
        return False


def trade_open(symbol: str, side: str, notional: float = None, qty: float = None,
               price: float = 0.0, stop=None, tp=None, time_stop_min=None) -> bool:
    size = f"${notional:,.2f}" if notional else f"{qty} units"
    lines = [
        f"{'🟢 BUY' if side == 'buy' else '🔴 SELL'} {symbol} — {size} @ ${price:,.2f}",
    ]
    if stop:
        lines.append(f"Stop: ${stop:,.2f}")
    if tp:
        lines.append(f"Take profit: ${tp:,.2f}")
    if time_stop_min:
        lines.append(f"Time stop: {int(time_stop_min) // 60}h {int(time_stop_min) % 60}m")
    lines.append("🤖 SMC bot")
    return _send("\n".join(lines))


def trade_close(symbol: str, reason: str, pnl: float, pnl_pct: float, equity: float = None) -> bool:
    emoji = "✅" if pnl >= 0 else "🛑"
    lines = [
        f"{emoji} CLOSED {symbol} [{reason}]",
        f"P&L: ${pnl:+,.2f} ({pnl_pct:+.2f}%)",
    ]
    if equity:
        lines.append(f"Equity: ${equity:,.2f}")
    lines.append("🤖 SMC bot")
    return _send("\n".join(lines))


def setup_seen(symbol: str, action: str, conf: float, reason: str, price: float = 0.0) -> bool:
    """Fired whenever the bot detects an SMC setup - traded or blocked."""
    p = f" @ ${price:,.2f}" if price else ""
    return _send(f"👁 Setup spotted: {action} {symbol}{p}\n"
                 f"Strength: {conf:.2f} | Gate: {reason}\n"
                 f"🤖 SMC bot")


def daily_summary(equity: float, open_positions: int, trades_today: int,
                  journal_stats: dict = None, extra: str = "",
                  governor: dict = None) -> bool:
    lines = [
        "📊 Daily bot summary",
        f"Equity: ${equity:,.2f}",
        f"Open positions: {open_positions} | Trades today: {trades_today}",
    ]
    if journal_stats:
        lines.append(
            f"Setup journal: {journal_stats.get('setups_logged', 0)} logged, "
            f"{journal_stats.get('settled', 0)} settled"
        )
        if journal_stats.get("settled_win_rate") is not None:
            lines.append(f"Journal win rate: {journal_stats['settled_win_rate']}%")
    if governor:
        state = "ACTIVE - hunting" if governor.get("avg_r", 0) > 0 else "STANDING DOWN (edge gone)"
        lines.append(f"SMC governor: {state} ({governor.get('avg_r', 0):+.2f}R over last {governor.get('n', 0)})")
    if extra:
        lines.append(extra)
    lines.append("🤖 SMC bot")
    return _send("\n".join(lines))


def test() -> bool:
    ok = _send("🔔 Bot connected to Telegram! You'll get trade alerts here.")
    if not ok:
        logging.getLogger(__name__).warning(
            "Telegram test failed: check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env, "
            "and that you pressed START in your bot's chat"
        )
    return ok
