"""
technical.py — Technical Analysis Phase for AlphaSwarm
========================================================
Fetches 1-year daily OHLCV data via yfinance, computes real indicators
using pandas-ta, and produces both a structured JSON payload for the chart
and a findings string for synthesis injection.

Indicators computed:
  Trend    : SMA20, SMA50, SMA200, EMA12, EMA26 — golden/death cross detection
  Momentum : RSI(14), MACD(12,26,9), Stochastic(14,3)
  Volatility: Bollinger Bands(20,2), ATR(14)
  Volume   : OBV, Volume SMA20, volume trend
  Support/Resistance: pivot points, 52-week high/low, key price levels
  Patterns : engulfing candles, doji, hammer, shooting star, gap detection
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

try:
    import yfinance as yf
    YFINANCE_OK = True
except Exception:
    YFINANCE_OK = False


# ─── TICKER RESOLUTION ────────────────────────────────────────────────────────

COMMON_TICKERS: dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "tesla": "TSLA",
    "nvidia": "NVDA", "netflix": "NFLX", "salesforce": "CRM", "adobe": "ADBE",
    "paypal": "PYPL", "shopify": "SHOP", "uber": "UBER", "lyft": "LYFT",
    "airbnb": "ABNB", "coinbase": "COIN", "palantir": "PLTR", "snowflake": "SNOW",
    "databricks": "DBX", "cloudflare": "NET", "okta": "OKTA", "zoom": "ZM",
    "slack": "WORK", "twitter": "TWTR", "snap": "SNAP", "pinterest": "PINS",
    "spotify": "SPOT", "amd": "AMD", "intel": "INTC", "qualcomm": "QCOM",
    "broadcom": "AVGO", "texas instruments": "TXN", "applied materials": "AMAT",
    "lam research": "LRCX", "asml": "ASML", "tsmc": "TSM", "samsung": "SSNLF",
    "jp morgan": "JPM", "jpmorgan": "JPM", "bank of america": "BAC",
    "wells fargo": "WFC", "goldman sachs": "GS", "morgan stanley": "MS",
    "visa": "V", "mastercard": "MA", "american express": "AXP",
    "berkshire": "BRK-B", "johnson & johnson": "JNJ", "pfizer": "PFE",
    "moderna": "MRNA", "eli lilly": "LLY", "unitedhealth": "UNH",
    "walmart": "WMT", "target": "TGT", "costco": "COST", "home depot": "HD",
    "boeing": "BA", "lockheed": "LMT", "raytheon": "RTX", "caterpillar": "CAT",
    "exxon": "XOM", "chevron": "CVX", "shell": "SHEL", "bp": "BP",
    "disney": "DIS", "comcast": "CMCSA", "at&t": "T", "verizon": "VZ",
    "openai": None, "anthropic": None, "spacex": None,  # private companies
}


def resolve_ticker(target: str) -> str | None:
    """
    Best-effort ticker resolution from a company name or raw ticker string.
    Returns None if the company appears to be private or unresolvable.
    """
    if not target:
        return None

    # Clean the target
    clean = target.strip()

    # Looks like a raw ticker already (1-5 uppercase chars)
    if re.match(r'^[A-Z]{1,5}(-[A-Z])?$', clean):
        return clean

    lower = clean.lower()

    # Check our known map first
    for name, ticker in COMMON_TICKERS.items():
        if name in lower:
            return ticker  # None means private

    # Try yfinance lookup as fallback
    if YFINANCE_OK:
        try:
            # Try the target as a ticker symbol directly
            candidate = re.sub(r'[^A-Za-z0-9]', '', clean[:6]).upper()
            if candidate:
                info = yf.Ticker(candidate).fast_info
                mkt_cap = getattr(info, 'market_cap', None)
                if mkt_cap and mkt_cap > 0:
                    return candidate
        except Exception:
            pass

    return None


def validate_target(target: str) -> dict[str, Any]:
    """
    Best-effort company validation for the homepage run gate.
    Returns whether the target is valid, public/private classification,
    and the resolved ticker when applicable.
    """
    clean = (target or "").strip()
    if not clean:
        return {
            "target": target,
            "is_valid": False,
            "is_public": False,
            "is_private": False,
            "ticker": None,
            "reason": "Enter a company name or ticker.",
        }

    lower = clean.lower()
    private_match = None
    for name, ticker in COMMON_TICKERS.items():
        if ticker is None and name in lower:
            private_match = name
            break
    if private_match:
        return {
            "target": target,
            "is_valid": True,
            "is_public": False,
            "is_private": True,
            "ticker": None,
            "reason": f"Identified as private company ({private_match.title()}); technical analysis will be skipped.",
        }

    ticker = resolve_ticker(clean)
    if not ticker:
        return {
            "target": target,
            "is_valid": False,
            "is_public": False,
            "is_private": False,
            "ticker": None,
            "reason": "Could not verify this as a real company or listed ticker.",
        }

    known_public_tickers = {t for t in COMMON_TICKERS.values() if t}
    if ticker in known_public_tickers:
        return {
            "target": target,
            "is_valid": True,
            "is_public": True,
            "is_private": False,
            "ticker": ticker,
            "reason": f"Validated as public company ({ticker}).",
        }

    df, fetch_error = fetch_ohlcv(ticker, period="3mo", interval="1d")
    if df is not None and not df.empty:
        return {
            "target": target,
            "is_valid": True,
            "is_public": True,
            "is_private": False,
            "ticker": ticker,
            "reason": f"Validated as public company ({ticker}).",
        }

    # Fallback check: if metadata exists, treat as real listed symbol even if OHLCV fetch failed.
    if YFINANCE_OK:
        try:
            info = yf.Ticker(ticker).info or {}
            if info.get("symbol") or info.get("shortName") or info.get("longName"):
                return {
                    "target": target,
                    "is_valid": True,
                    "is_public": True,
                    "is_private": False,
                    "ticker": ticker,
                    "reason": (
                        f"Validated as public company ({ticker}), but market data fetch is currently limited"
                        f"{': ' + fetch_error if fetch_error else ''}."
                    ),
                }
        except Exception:
            pass

    # Final offline fallback: allow known built-in public tickers when live market checks are unavailable.
    if ticker in known_public_tickers:
        return {
            "target": target,
            "is_valid": True,
            "is_public": True,
            "is_private": False,
            "ticker": ticker,
            "reason": (
                f"Validated as public company ({ticker}) from built-in mapping; "
                "live market verification is currently unavailable."
            ),
        }

    return {
        "target": target,
        "is_valid": False,
        "is_public": False,
        "is_private": False,
        "ticker": ticker,
        "reason": (
            "Ticker/company could not be validated from market data."
            + (f" ({fetch_error})" if fetch_error else "")
        ),
    }


# ─── CORE TECHNICAL ANALYSIS ──────────────────────────────────────────────────

import logging as _logging
_ta_log = _logging.getLogger("alphaswarm.technical")
if not _ta_log.handlers:
    _handler = _logging.StreamHandler()
    _handler.setFormatter(_logging.Formatter("[TECHNICAL] %(levelname)s %(message)s"))
    _ta_log.addHandler(_handler)
    _ta_log.setLevel(_logging.WARNING)


def _normalise_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """Flatten MultiIndex columns, title-case names, keep OHLCV, coerce to float."""
    if df is None or df.empty:
        return None
    # Flatten MultiIndex (yfinance >= 0.2.48 with multiple tickers or download())
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    # Normalise to Title case: 'close' → 'Close', 'Adj Close' stays 'Adj Close'
    df.columns = [str(c).strip().title() for c in df.columns]
    keep = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    if len(keep) < 5:
        return None
    df = df[keep].copy()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna()
    return df if len(df) >= 20 else None


def _yahoo_direct(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """
    Fetch OHLCV data by calling the Yahoo Finance v8 chart API directly via requests.
    This bypasses yfinance's internal session/crumb management which breaks silently
    in yfinance 1.x when cookie initialisation fails.
    """
    import requests as _requests
    from datetime import datetime, timezone as _tz

    # Map period strings to seconds
    period_seconds = {
        "1d": 86400, "5d": 432000, "1mo": 2592000, "3mo": 7776000,
        "6mo": 15552000, "1y": 31536000, "2y": 63072000, "5y": 157680000,
    }
    secs = period_seconds.get(period, 31536000)
    end_ts = int(datetime.now(_tz.utc).timestamp())
    start_ts = end_ts - secs

    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
    ]
    params = {
        "interval": interval,
        "period1": start_ts,
        "period2": end_ts,
        "includePrePost": "false",
        "events": "div,splits",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://finance.yahoo.com",
        "Referer": "https://finance.yahoo.com/",
    }

    for url in urls:
        try:
            resp = _requests.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code != 200:
                _ta_log.warning("yahoo_direct HTTP %d for %s", resp.status_code, ticker)
                continue
            data = resp.json()
            result = (data.get("chart") or {}).get("result") or []
            if not result:
                error_msg = (data.get("chart") or {}).get("error") or "no result"
                _ta_log.warning("yahoo_direct no result for %s: %s", ticker, error_msg)
                continue
            r = result[0]
            timestamps = r.get("timestamp") or []
            quote = (r.get("indicators") or {}).get("quote") or [{}]
            q = quote[0]
            adj_close = ((r.get("indicators") or {}).get("adjclose") or [{}])
            adj = (adj_close[0].get("adjclose") or []) if adj_close else []

            opens   = q.get("open", [])
            highs   = q.get("high", [])
            lows    = q.get("low", [])
            closes  = q.get("close", [])
            volumes = q.get("volume", [])

            if not timestamps or not closes:
                continue

            # Use adjusted close if available
            close_data = adj if len(adj) == len(timestamps) else closes

            df = pd.DataFrame({
                "Open":   opens,
                "High":   highs,
                "Low":    lows,
                "Close":  close_data,
                "Volume": volumes,
            }, index=pd.to_datetime(timestamps, unit="s", utc=True))
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)

            # Coerce and clean
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna()
            if len(df) >= 20:
                _ta_log.warning("yahoo_direct OK: %s rows=%d", ticker, len(df))
                return df
        except Exception as exc:
            _ta_log.warning("yahoo_direct error for %s via %s: %s", ticker, url, exc)

    return None


def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> tuple[pd.DataFrame | None, str | None]:
    """
    Fetch OHLCV data using three strategies in order:
      1. Direct Yahoo Finance v8 API via requests (most reliable, bypasses yfinance auth bugs)
      2. yfinance Ticker.history()
      3. yfinance download() legacy fallback

    Returns (DataFrame, None) on success or (None, error_string) on failure.
    """
    if not YFINANCE_OK:
        # yfinance not installed, but we can still try direct API
        _ta_log.warning("yfinance not installed, trying direct API only")

    last_error: str = "all fetch strategies returned empty data"

    # ── Strategy 1: Direct Yahoo Finance API (bypasses yfinance cookie bugs) ──
    try:
        df = _yahoo_direct(ticker, period=period, interval=interval)
        if df is not None:
            return df, None
        last_error = f"Direct Yahoo API returned empty data for {ticker}"
    except Exception as exc:
        last_error = f"Direct Yahoo API failed: {exc}"
        _ta_log.warning("fetch_ohlcv [direct] error: %s — %s", ticker, exc)

    if not YFINANCE_OK:
        return None, last_error + ". Install yfinance: pip install yfinance"

    # ── Strategy 2: yfinance Ticker.history() ────────────────────────────────
    try:
        t = yf.Ticker(ticker)
        raw = t.history(period=period, interval=interval, auto_adjust=True, timeout=20)
        df = _normalise_df(raw)
        if df is not None:
            _ta_log.warning("fetch_ohlcv [Ticker.history] OK: %s rows=%d", ticker, len(df))
            return df, None
        last_error = f"Ticker.history() returned empty data for {ticker}"
        _ta_log.warning("fetch_ohlcv [Ticker.history] empty: %s", ticker)
    except Exception as exc:
        last_error = f"Ticker.history() failed: {exc}"
        _ta_log.warning("fetch_ohlcv [Ticker.history] error: %s — %s", ticker, exc)

    # ── Strategy 3: yfinance download() ──────────────────────────────────────
    try:
        kwargs = dict(period=period, interval=interval, auto_adjust=True,
                      progress=False, timeout=20)
        try:
            raw2 = yf.download(ticker, multi_level_index=False, **kwargs)
        except TypeError:
            raw2 = yf.download(ticker, **kwargs)
        df2 = _normalise_df(raw2)
        if df2 is not None:
            _ta_log.warning("fetch_ohlcv [yf.download] OK: %s rows=%d", ticker, len(df2))
            return df2, None
        last_error = f"yf.download() returned empty data for {ticker}"
        _ta_log.warning("fetch_ohlcv [yf.download] empty: %s", ticker)
    except Exception as exc:
        last_error = f"yf.download() failed: {exc}"
        _ta_log.warning("fetch_ohlcv [yf.download] error: %s — %s", ticker, exc)

    _ta_log.warning("fetch_ohlcv ALL strategies failed for %s: %s", ticker, last_error)
    return None, last_error


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute all technical indicators on the dataframe.
    Returns a dict of named indicator series/values.
    """
    close = df['Close']
    high  = df['High']
    low   = df['Low']
    vol   = df['Volume']
    n     = len(df)

    result: dict[str, Any] = {}

    # ── Moving Averages ────────────────────────────────────────────────────────
    for period in [20, 50, 200]:
        if n >= period:
            result[f'SMA{period}'] = close.rolling(period).mean()
        else:
            result[f'SMA{period}'] = pd.Series([np.nan]*n, index=df.index)

    for period in [12, 26]:
        result[f'EMA{period}'] = close.ewm(span=period, adjust=False).mean()

    # ── RSI(14) ────────────────────────────────────────────────────────────────
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    result['RSI14'] = 100 - (100 / (1 + rs))

    # ── MACD(12,26,9) ─────────────────────────────────────────────────────────
    macd_line = result['EMA12'] - result['EMA26']
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    result['MACD'] = macd_line
    result['MACD_signal'] = signal_line
    result['MACD_hist'] = macd_line - signal_line

    # ── Bollinger Bands(20,2) ─────────────────────────────────────────────────
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    result['BB_upper'] = bb_mid + 2 * bb_std
    result['BB_mid']   = bb_mid
    result['BB_lower'] = bb_mid - 2 * bb_std
    bb_range = result['BB_upper'] - result['BB_lower']
    result['BB_pct'] = (close - result['BB_lower']) / bb_range.replace(0, np.nan)
    result['BB_width'] = bb_range / bb_mid.replace(0, np.nan)

    # ── ATR(14) ───────────────────────────────────────────────────────────────
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    result['ATR14'] = tr.rolling(14).mean()

    # ── Stochastic(14,3) ──────────────────────────────────────────────────────
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_range = high14 - low14
    result['Stoch_K'] = 100 * (close - low14) / stoch_range.replace(0, np.nan)
    result['Stoch_D'] = result['Stoch_K'].rolling(3).mean()

    # ── OBV ───────────────────────────────────────────────────────────────────
    direction = np.sign(close.diff().fillna(0))
    result['OBV'] = (direction * vol).cumsum()

    # ── Volume SMA ────────────────────────────────────────────────────────────
    result['Vol_SMA20'] = vol.rolling(20).mean()

    return result


def _safe_float(val: Any) -> float | None:
    """Convert to float safely, returning None on failure."""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _fmt(val: Any, decimals: int = 2, prefix: str = "", suffix: str = "") -> str:
    """Format a float for display."""
    f = _safe_float(val)
    if f is None:
        return "N/A"
    return f"{prefix}{f:.{decimals}f}{suffix}"


def detect_patterns(df: pd.DataFrame) -> list[dict[str, str]]:
    """Detect candlestick patterns on the last 10 candles."""
    patterns: list[dict[str, str]] = []
    if len(df) < 3:
        return patterns

    recent = df.tail(10).copy()
    o = recent['Open'].values
    h = recent['High'].values
    l = recent['Low'].values
    c = recent['Close'].values

    for i in range(1, len(recent)):
        body = abs(c[i] - o[i])
        candle_range = h[i] - l[i] if h[i] != l[i] else 0.0001
        body_pct = body / candle_range

        # Doji (body < 10% of range)
        if body_pct < 0.10:
            patterns.append({"name": "Doji", "type": "neutral",
                             "desc": "Indecision — buyers and sellers in equilibrium"})

        # Hammer (bullish reversal — small body, long lower wick)
        lower_wick = min(o[i], c[i]) - l[i]
        upper_wick = h[i] - max(o[i], c[i])
        if body_pct < 0.35 and lower_wick > 2 * body and upper_wick < body:
            patterns.append({"name": "Hammer", "type": "bullish",
                             "desc": "Potential bullish reversal after downtrend"})

        # Shooting Star (bearish reversal)
        if body_pct < 0.35 and upper_wick > 2 * body and lower_wick < body:
            patterns.append({"name": "Shooting Star", "type": "bearish",
                             "desc": "Potential bearish reversal — bulls rejected at highs"})

        # Bullish Engulfing
        if (i >= 1 and c[i] > o[i] and c[i-1] < o[i-1] and
                c[i] > o[i-1] and o[i] < c[i-1]):
            patterns.append({"name": "Bullish Engulfing", "type": "bullish",
                             "desc": "Strong bullish reversal signal — buyers took full control"})

        # Bearish Engulfing
        if (i >= 1 and c[i] < o[i] and c[i-1] > o[i-1] and
                c[i] < o[i-1] and o[i] > c[i-1]):
            patterns.append({"name": "Bearish Engulfing", "type": "bearish",
                             "desc": "Strong bearish reversal signal — sellers overwhelmed buyers"})

        # Gap Up
        if i >= 1 and l[i] > h[i-1]:
            patterns.append({"name": "Gap Up", "type": "bullish",
                             "desc": "Price gapped up — strong demand, often momentum continuation"})

        # Gap Down
        if i >= 1 and h[i] < l[i-1]:
            patterns.append({"name": "Gap Down", "type": "bearish",
                             "desc": "Price gapped down — strong selling pressure"})

    # Deduplicate by name, keep last occurrence
    seen = {}
    for p in patterns:
        seen[p["name"]] = p
    return list(seen.values())[-5:]  # max 5 most recent


def compute_support_resistance(df: pd.DataFrame) -> dict[str, Any]:
    """Compute key S/R levels from recent price action."""
    close = df['Close']
    high  = df['High']
    low   = df['Low']
    current = _safe_float(close.iloc[-1])

    # 52-week high/low
    wk52_high = _safe_float(high.tail(252).max())
    wk52_low  = _safe_float(low.tail(252).min())

    # Monthly pivots (last 20 days)
    recent_high = _safe_float(high.tail(20).max())
    recent_low  = _safe_float(low.tail(20).min())

    # Classic pivot point (yesterday)
    pivot = None
    r1 = r2 = s1 = s2 = None
    if len(df) >= 2:
        yesterday = df.iloc[-2]
        p = (_safe_float(yesterday['High']) + _safe_float(yesterday['Low']) + _safe_float(yesterday['Close'])) / 3
        pivot = p
        if _safe_float(yesterday['High']) and _safe_float(yesterday['Low']):
            r1 = 2 * p - _safe_float(yesterday['Low'])
            r2 = p + (_safe_float(yesterday['High']) - _safe_float(yesterday['Low']))
            s1 = 2 * p - _safe_float(yesterday['High'])
            s2 = p - (_safe_float(yesterday['High']) - _safe_float(yesterday['Low']))

    # Distance from 52-week levels
    dist_from_high = ((current - wk52_high) / wk52_high * 100) if wk52_high and current else None
    dist_from_low  = ((current - wk52_low) / wk52_low * 100) if wk52_low and current else None

    return {
        "wk52_high": wk52_high,
        "wk52_low":  wk52_low,
        "recent_high": recent_high,
        "recent_low":  recent_low,
        "pivot": pivot,
        "r1": r1, "r2": r2,
        "s1": s1, "s2": s2,
        "dist_from_52w_high_pct": dist_from_high,
        "dist_from_52w_low_pct":  dist_from_low,
        "current_price": current,
    }


def generate_signals(df: pd.DataFrame, indicators: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable technical signals with explanations."""
    signals: list[dict[str, str]] = []
    close = df['Close']
    current = _safe_float(close.iloc[-1])
    if current is None:
        return signals

    # Helper to get last valid value from a series
    def last(key: str) -> float | None:
        s = indicators.get(key)
        if s is None:
            return None
        vals = s.dropna()
        return _safe_float(vals.iloc[-1]) if len(vals) else None

    def prev(key: str) -> float | None:
        s = indicators.get(key)
        if s is None:
            return None
        vals = s.dropna()
        return _safe_float(vals.iloc[-2]) if len(vals) >= 2 else None

    sma20  = last('SMA20')
    sma50  = last('SMA50')
    sma200 = last('SMA200')
    rsi    = last('RSI14')
    macd   = last('MACD')
    macd_s = last('MACD_signal')
    macd_h = last('MACD_hist')
    prev_macd_h = prev('MACD_hist')
    stoch_k = last('Stoch_K')
    stoch_d = last('Stoch_D')
    bb_pct  = last('BB_pct')
    bb_w    = last('BB_width')
    atr     = last('ATR14')
    obv_now = last('OBV')

    # ── Trend signals ──────────────────────────────────────────────────────────
    if sma20 and sma50:
        if sma20 > sma50:
            signals.append({"signal": "Golden Cross (SMA20 > SMA50)", "type": "bullish",
                            "strength": "strong",
                            "detail": f"Short-term momentum (${sma20:.2f}) above medium-term trend (${sma50:.2f}) — uptrend intact"})
        else:
            signals.append({"signal": "Death Cross (SMA20 < SMA50)", "type": "bearish",
                            "strength": "strong",
                            "detail": f"Short-term (${sma20:.2f}) below medium-term trend (${sma50:.2f}) — downtrend pressure"})

    if sma200:
        if current > sma200:
            pct_above = (current - sma200) / sma200 * 100
            signals.append({"signal": "Above 200-day SMA", "type": "bullish",
                            "strength": "moderate",
                            "detail": f"Price {pct_above:.1f}% above long-term average (${sma200:.2f}) — secular uptrend"})
        else:
            pct_below = (sma200 - current) / sma200 * 100
            signals.append({"signal": "Below 200-day SMA", "type": "bearish",
                            "strength": "moderate",
                            "detail": f"Price {pct_below:.1f}% below long-term average (${sma200:.2f}) — bearish structure"})

    # ── RSI signals ────────────────────────────────────────────────────────────
    if rsi is not None:
        if rsi >= 70:
            signals.append({"signal": f"RSI Overbought ({rsi:.1f})", "type": "bearish",
                            "strength": "moderate",
                            "detail": "RSI above 70 — momentum stretched, mean reversion risk elevated"})
        elif rsi <= 30:
            signals.append({"signal": f"RSI Oversold ({rsi:.1f})", "type": "bullish",
                            "strength": "moderate",
                            "detail": "RSI below 30 — heavily sold, potential bounce or value entry"})
        elif 40 <= rsi <= 60:
            signals.append({"signal": f"RSI Neutral ({rsi:.1f})", "type": "neutral",
                            "strength": "weak",
                            "detail": "RSI in neutral zone — no strong momentum bias"})
        elif rsi > 60:
            signals.append({"signal": f"RSI Bullish Momentum ({rsi:.1f})", "type": "bullish",
                            "strength": "moderate",
                            "detail": "RSI in bullish momentum zone (60-70) without being overbought"})
        else:
            signals.append({"signal": f"RSI Bearish Momentum ({rsi:.1f})", "type": "bearish",
                            "strength": "moderate",
                            "detail": "RSI in bearish zone (30-40) — selling pressure persists"})

    # ── MACD signals ───────────────────────────────────────────────────────────
    if macd is not None and macd_s is not None:
        if macd > macd_s:
            signals.append({"signal": "MACD Bullish", "type": "bullish",
                            "strength": "moderate",
                            "detail": f"MACD ({macd:.3f}) above signal line ({macd_s:.3f}) — bullish momentum"})
        else:
            signals.append({"signal": "MACD Bearish", "type": "bearish",
                            "strength": "moderate",
                            "detail": f"MACD ({macd:.3f}) below signal line ({macd_s:.3f}) — bearish momentum"})

    if macd_h is not None and prev_macd_h is not None:
        if macd_h > 0 and prev_macd_h <= 0:
            signals.append({"signal": "MACD Bullish Crossover", "type": "bullish",
                            "strength": "strong",
                            "detail": "MACD histogram just crossed above zero — fresh buy signal"})
        elif macd_h < 0 and prev_macd_h >= 0:
            signals.append({"signal": "MACD Bearish Crossover", "type": "bearish",
                            "strength": "strong",
                            "detail": "MACD histogram just crossed below zero — fresh sell signal"})

    # ── Bollinger Band signals ─────────────────────────────────────────────────
    if bb_pct is not None:
        if bb_pct >= 1.0:
            signals.append({"signal": "Above Upper Bollinger Band", "type": "bearish",
                            "strength": "moderate",
                            "detail": "Price exceeds upper BB — statistically extended, pullback likely"})
        elif bb_pct <= 0.0:
            signals.append({"signal": "Below Lower Bollinger Band", "type": "bullish",
                            "strength": "moderate",
                            "detail": "Price below lower BB — oversold on volatility basis, mean-reversion candidate"})

    if bb_w is not None and bb_w < 0.05:
        signals.append({"signal": "Bollinger Squeeze", "type": "neutral",
                        "strength": "moderate",
                        "detail": "Bands are tight — low volatility, large directional move incoming"})

    # ── Stochastic signals ─────────────────────────────────────────────────────
    if stoch_k is not None and stoch_d is not None:
        if stoch_k >= 80 and stoch_d >= 80:
            signals.append({"signal": f"Stochastic Overbought (K:{stoch_k:.0f} D:{stoch_d:.0f})", "type": "bearish",
                            "strength": "weak",
                            "detail": "Stochastic in overbought zone — confirms RSI reading"})
        elif stoch_k <= 20 and stoch_d <= 20:
            signals.append({"signal": f"Stochastic Oversold (K:{stoch_k:.0f} D:{stoch_d:.0f})", "type": "bullish",
                            "strength": "weak",
                            "detail": "Stochastic in oversold zone — momentum exhaustion on downside"})

    # Limit to most meaningful
    return signals[:10]


def score_technical(signals: list[dict]) -> tuple[float, str]:
    """
    Score 1-10 from signals, return (score, direction).
    Bullish signals add, bearish subtract, with strength weighting.
    """
    strength_weight = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}
    score = 5.0  # neutral baseline
    for s in signals:
        w = strength_weight.get(s.get("strength", "weak"), 0.5)
        if s.get("type") == "bullish":
            score += w
        elif s.get("type") == "bearish":
            score -= w

    score = max(1.0, min(10.0, score))
    direction = "BULLISH" if score >= 6.0 else "BEARISH" if score <= 4.0 else "NEUTRAL"
    return round(score, 1), direction


def build_findings_text(
    ticker: str,
    current_price: float | None,
    signals: list[dict],
    patterns: list[dict],
    sr: dict[str, Any],
    indicators: dict[str, Any],
    score: float,
    direction: str,
    df: pd.DataFrame,
) -> str:
    """
    Build a human-readable findings string for synthesis injection.
    Mirrors the format of other agents' output_sections.
    """
    close = df['Close']
    n = len(df)

    def last_val(key: str) -> float | None:
        s = indicators.get(key)
        if s is None:
            return None
        v = s.dropna()
        return _safe_float(v.iloc[-1]) if len(v) else None

    rsi    = last_val('RSI14')
    macd   = last_val('MACD')
    macd_s = last_val('MACD_signal')
    sma20  = last_val('SMA20')
    sma50  = last_val('SMA50')
    sma200 = last_val('SMA200')
    atr    = last_val('ATR14')
    bb_pct = last_val('BB_pct')

    # Price change stats
    price_1w  = _safe_float(close.iloc[-6]) if n >= 6 else None
    price_1m  = _safe_float(close.iloc[-22]) if n >= 22 else None
    price_3m  = _safe_float(close.iloc[-66]) if n >= 66 else None
    price_6m  = _safe_float(close.iloc[-132]) if n >= 132 else None
    cp = current_price

    def pct_chg(old: float | None, new: float | None) -> str:
        if old and new and old != 0:
            return f"{((new-old)/old*100):+.1f}%"
        return "N/A"

    bullish_sigs = [s for s in signals if s.get("type") == "bullish"]
    bearish_sigs = [s for s in signals if s.get("type") == "bearish"]
    bull_patterns = [p for p in patterns if p.get("type") == "bullish"]
    bear_patterns = [p for p in patterns if p.get("type") == "bearish"]

    lines = [
        f"## TREND_ANALYSIS",
        f"- Direction: {direction} | Technical Score: {score}/10",
        f"- Current Price: {_fmt(cp, 2, '$')} | 52w High: {_fmt(sr.get('wk52_high'), 2, '$')} | 52w Low: {_fmt(sr.get('wk52_low'), 2, '$')}",
        f"- Distance from 52w high: {_fmt(sr.get('dist_from_52w_high_pct'), 1, suffix='%')} | from 52w low: {_fmt(sr.get('dist_from_52w_low_pct'), 1, suffix='%')}",
        f"- SMA20: {_fmt(sma20, 2, '$')} | SMA50: {_fmt(sma50, 2, '$')} | SMA200: {_fmt(sma200, 2, '$')}",
        f"- 1-Week: {pct_chg(price_1w, cp)} | 1-Month: {pct_chg(price_1m, cp)} | 3-Month: {pct_chg(price_3m, cp)} | 6-Month: {pct_chg(price_6m, cp)}",
        "",
        f"## MOMENTUM_INDICATORS",
        f"- RSI(14): {_fmt(rsi, 1)} — {'Overbought >70' if rsi and rsi >= 70 else 'Oversold <30' if rsi and rsi <= 30 else 'Neutral 30-70'}",
        f"- MACD: {_fmt(macd, 4)} | Signal: {_fmt(macd_s, 4)} | {'Bullish' if macd and macd_s and macd > macd_s else 'Bearish'} crossover",
        f"- Bollinger %B: {_fmt(bb_pct, 2)} — {'Near upper band (stretched)' if bb_pct and bb_pct > 0.8 else 'Near lower band (oversold)' if bb_pct and bb_pct < 0.2 else 'Mid-band (neutral)'}",
        f"- ATR(14): {_fmt(atr, 2, '$')} — daily volatility range",
        "",
        f"## SUPPORT_RESISTANCE",
        f"- Key Resistance: R1={_fmt(sr.get('r1'), 2, '$')} | R2={_fmt(sr.get('r2'), 2, '$')}",
        f"- Key Support: S1={_fmt(sr.get('s1'), 2, '$')} | S2={_fmt(sr.get('s2'), 2, '$')}",
        f"- Pivot: {_fmt(sr.get('pivot'), 2, '$')}",
        "",
        f"## SIGNALS",
    ]

    for s in signals:
        icon = "↑" if s.get("type") == "bullish" else "↓" if s.get("type") == "bearish" else "→"
        lines.append(f"- {icon} [{s.get('strength','').upper()}] {s.get('signal')}: {s.get('detail')}")

    lines.append("")
    lines.append("## CANDLESTICK_PATTERNS")
    if patterns:
        for p in patterns:
            icon = "↑" if p.get("type") == "bullish" else "↓" if p.get("type") == "bearish" else "→"
            lines.append(f"- {icon} {p.get('name')}: {p.get('desc')}")
    else:
        lines.append("- No significant patterns detected in recent candles")

    lines.append("")
    lines.append("## TECHNICAL_VERDICT")
    bull_count = len(bullish_sigs)
    bear_count = len(bearish_sigs)
    lines.append(f"- {bull_count} bullish signals vs {bear_count} bearish signals → {direction}")
    lines.append(f"- Technical Score: {score}/10 (1=extreme bear, 10=extreme bull, 5=neutral)")
    lines.append(f"- Ticker analyzed: {ticker} | Data: 1-year daily candles | As of: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("## CONFIDENCE")
    lines.append(f"High — technical data sourced directly from market data (yfinance). {len(df)} trading days analyzed.")
    lines.append("")
    lines.append("## TOP_FINDING")
    # Pick the strongest signal as top finding
    top = next((s for s in signals if s.get("strength") == "strong"), signals[0] if signals else None)
    if top:
        lines.append(f"{top.get('signal')}: {top.get('detail')}")

    return "\n".join(lines)


def serialize_chart_data(df: pd.DataFrame, indicators: dict[str, Any], ticker: str) -> dict[str, Any]:
    """
    Build JSON-serializable chart payload for the frontend candlestick chart.
    All values rounded to 4 decimal places for payload efficiency.
    """
    def s2list(key: str) -> list[float | None]:
        series = indicators.get(key)
        if series is None:
            return [None] * len(df)
        return [_safe_float(v) for v in series]

    timestamps = [int(ts.timestamp() * 1000) for ts in df.index]
    if hasattr(df.index[0], 'to_pydatetime'):
        timestamps = [int(pd.Timestamp(ts).timestamp() * 1000) for ts in df.index]

    candles = []
    for i, (ts, row) in enumerate(zip(timestamps, df.itertuples())):
        candles.append({
            "t": ts,
            "o": round(float(row.Open), 4),
            "h": round(float(row.High), 4),
            "l": round(float(row.Low), 4),
            "c": round(float(row.Close), 4),
            "v": int(row.Volume),
        })

    def zip_ts(key: str) -> list[dict]:
        vals = s2list(key)
        return [{"t": t, "v": round(v, 4) if v is not None else None}
                for t, v in zip(timestamps, vals)]

    return {
        "ticker": ticker,
        "candles": candles,
        "indicators": {
            "SMA20":    zip_ts("SMA20"),
            "SMA50":    zip_ts("SMA50"),
            "SMA200":   zip_ts("SMA200"),
            "BB_upper": zip_ts("BB_upper"),
            "BB_mid":   zip_ts("BB_mid"),
            "BB_lower": zip_ts("BB_lower"),
            "RSI14":    zip_ts("RSI14"),
            "MACD":     zip_ts("MACD"),
            "MACD_signal": zip_ts("MACD_signal"),
            "MACD_hist":   zip_ts("MACD_hist"),
            "Volume":   [{"t": t, "v": c["v"]} for t, c in zip(timestamps, candles)],
            "Vol_SMA20": zip_ts("Vol_SMA20"),
        },
    }


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def run_technical_analysis(target: str) -> dict[str, Any]:
    """
    Full pipeline: resolve ticker → fetch data → compute indicators →
    generate signals → build findings + chart data.

    Returns a dict with:
      - ticker (str | None)
      - is_public (bool)
      - findings (str)
      - chart_data (dict)
      - signals (list)
      - patterns (list)
      - support_resistance (dict)
      - technical_score (float)
      - technical_direction (str)
      - error (str | None)
    """
    ticker = resolve_ticker(target)

    if ticker is None:
        return {
            "ticker": None,
            "is_public": False,
            "findings": (
                "## TECHNICAL_ANALYSIS\n"
                f"- Status: SKIPPED — '{target}' appears to be a private company with no publicly traded ticker.\n"
                "- Technical analysis requires exchange-listed securities with market price data.\n"
                "- Fundamental and qualitative analysis above remains applicable.\n\n"
                "## CONFIDENCE\nN/A — private company\n\n## TOP_FINDING\nCompany is not publicly traded; no chart data available."
            ),
            "chart_data": None,
            "signals": [],
            "patterns": [],
            "support_resistance": {},
            "technical_score": 5.0,
            "technical_direction": "NEUTRAL",
            "error": "private_company",
        }

    # Fetch data — returns (DataFrame, None) or (None, error_string)
    df, fetch_error = fetch_ohlcv(ticker, period="1y", interval="1d")
    if df is None:
        error_detail = fetch_error or "unknown error"
        return {
            "ticker": ticker,
            "is_public": True,
            "findings": (
                f"## TECHNICAL_ANALYSIS\n"
                f"- Ticker: {ticker}\n"
                f"- Status: DATA FETCH FAILED — {error_detail}\n"
                "- This may be a Yahoo Finance rate limit or network issue. Try again in a few minutes.\n"
                "- Fundamental analysis above is unaffected.\n\n"
                "## CONFIDENCE\nLow — no data available\n\n"
                f"## TOP_FINDING\nPrice data unavailable: {error_detail}"
            ),
            "chart_data": None,
            "signals": [],
            "patterns": [],
            "support_resistance": {},
            "technical_score": 5.0,
            "technical_direction": "NEUTRAL",
            "error": f"data_fetch_failed: {error_detail}",
        }

    # Compute everything
    indicators = compute_indicators(df)
    patterns   = detect_patterns(df)
    sr         = compute_support_resistance(df)
    signals    = generate_signals(df, indicators)
    score, direction = score_technical(signals)
    current_price = _safe_float(df['Close'].iloc[-1])

    findings = build_findings_text(
        ticker=ticker,
        current_price=current_price,
        signals=signals,
        patterns=patterns,
        sr=sr,
        indicators=indicators,
        score=score,
        direction=direction,
        df=df,
    )

    chart_data = serialize_chart_data(df, indicators, ticker)

    return {
        "ticker": ticker,
        "is_public": True,
        "findings": findings,
        "chart_data": chart_data,
        "signals": signals,
        "patterns": patterns,
        "support_resistance": sr,
        "technical_score": score,
        "technical_direction": direction,
        "error": None,
    }
