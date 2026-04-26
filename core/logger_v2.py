import logging
import os


def setup_logger(name: str, log_file: str | None = None, mode: str = 'w') -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        logger.handlers.clear()

    fmt = logging.Formatter('%(message)s')

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        fh = logging.FileHandler(log_file, mode=mode)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def log_open(
    logger: logging.Logger,
    direction: str,
    ts,
    entry: float,
    sl: float,
    tp: float,
) -> None:
    side = 'LONG' if direction == 'long' else 'SHORT'
    pct_to_tp = abs(tp - entry) / entry * 100
    pct_to_sl = abs(entry - sl) / entry * 100
    logger.info(
        f"[OPEN]  {side} | ts={ts} | entry={entry:.2f} | sl={sl:.2f} | tp={tp:.2f} "
        f"| pct_to_tp={pct_to_tp:.2f}% | pct_to_sl={pct_to_sl:.2f}%"
    )


def log_close(
    logger: logging.Logger,
    direction: str,
    entry: float,
    exit_price: float,
    reason: str,
    net: float,
    equity: float,
    fee_usd: float = 0.0,
) -> None:
    side = 'LONG' if direction == 'long' else 'SHORT'
    sign = '+' if net >= 0 else ''
    fee_str = f" | fee={fee_usd:.2f} USD" if fee_usd else ''
    logger.info(
        f"[CLOSE] {side} | entry={entry:.2f} | exit={exit_price:.2f} | reason={reason}"
        f"{fee_str} | net={sign}{net:.2f} USD | equity={equity:.2f} USD"
    )
