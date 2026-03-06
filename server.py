"""
FTSE MIB Agent — Backend Server
Scarica dati reali da Yahoo Finance (yfinance) — completamente gratuito,
nessuna API key necessaria, supporto nativo per Borsa Italiana (.MI).

Installazione:
    pip install flask flask-cors yfinance

Avvio:
    python server.py
"""

import json
import os
import yfinance as yf
from datetime import datetime, timedelta
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

TITOLI = {
    "ENI":   {"name": "Eni SpA",                "yf_ticker": "ENI.MI",   "category": "Energia"},
    "ENEL":  {"name": "Enel SpA",               "yf_ticker": "ENEL.MI",  "category": "Utilities"},
    "ISP":   {"name": "Intesa Sanpaolo",         "yf_ticker": "ISP.MI",   "category": "Bancario"},
    "UCG":   {"name": "UniCredit SpA",           "yf_ticker": "UCG.MI",   "category": "Bancario"},
    "STLAM": {"name": "Stellantis NV",           "yf_ticker": "STLAM.MI", "category": "Automotive"},
    "RACE":  {"name": "Ferrari NV",              "yf_ticker": "RACE.MI",  "category": "Automotive"},
    "PRY":   {"name": "Prysmian SpA",            "yf_ticker": "PRY.MI",   "category": "Industriale"},
    "BMED":  {"name": "Mediobanca SpA",          "yf_ticker": "BMED.MI",  "category": "Bancario"},
    "G":     {"name": "Assicurazioni Generali",  "yf_ticker": "G.MI",     "category": "Assicurativo"},
    "LDO":   {"name": "Leonardo SpA",            "yf_ticker": "LDO.MI",   "category": "Difesa"},
    "STMMI": {"name": "STMicroelectronics",      "yf_ticker": "STMMI.MI", "category": "Tecnologia"},
    "NEXI":  {"name": "Nexi SpA",                "yf_ticker": "NEXI.MI",  "category": "Tecnologia"},
}

CACHE_FILE = "cache_prezzi.json"
CACHE_TTL_MINUTES = 60


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)

def cache_valid(entry):
    if "timestamp" not in entry:
        return False
    ts = datetime.fromisoformat(entry["timestamp"])
    return datetime.now() - ts < timedelta(minutes=CACHE_TTL_MINUTES)

def fetch_daily(yf_ticker):
    ticker = yf.Ticker(yf_ticker)
    hist = ticker.history(period="6mo")
    if hist.empty:
        raise ValueError(f"Nessun dato per {yf_ticker}")
    return [round(float(p), 4) for p in hist["Close"].tolist()]

def sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = p * k + e * (1 - k)
    return round(e, 4)

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent = changes[-period:]
    gains = sum(c for c in recent if c > 0) / period
    losses = abs(sum(c for c in recent if c < 0)) / period
    if losses == 0:
        return 100.0
    return round(100 - 100 / (1 + gains / losses), 1)

def macd(prices):
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    if e12 is None or e26 is None:
        return None
    return round(e12 - e26, 4)

def bollinger(prices, period=20):
    if len(prices) < period:
        return None
    sl = prices[-period:]
    m = sum(sl) / period
    std = (sum((p - m) ** 2 for p in sl) / period) ** 0.5
    return {"upper": round(m + 2 * std, 4), "middle": round(m, 4), "lower": round(m - 2 * std, 4)}

def analyze(ticker, prices):
    current = prices[-1]
    prev    = prices[-2]
    p22     = prices[-22] if len(prices) >= 22 else prices[0]
    s20, s50, e20 = sma(prices, 20), sma(prices, 50), ema(prices, 20)
    r, m, bb = rsi(prices), macd(prices), bollinger(prices)
    change1d = round((current - prev) / prev * 100, 2)
    change1m = round((current - p22) / p22 * 100, 2)
    signals, bull_count, bear_count = [], 0, 0

    if s20 and s50:
        ps20, ps50 = sma(prices[:-1], 20), sma(prices[:-1], 50)
        if s20 > s50 and ps20 <= ps50:
            signals.append({"type": "bull", "label": "Golden Cross", "desc": "SMA20 ha appena superato SMA50"}); bull_count += 2
        elif s20 < s50 and ps20 >= ps50:
            signals.append({"type": "bear", "label": "Death Cross", "desc": "SMA20 ha appena perso SMA50"}); bear_count += 2
        elif s20 > s50:
            signals.append({"type": "bull", "label": "Trend Rialzista", "desc": "SMA20 sopra SMA50"}); bull_count += 1
        else:
            signals.append({"type": "bear", "label": "Trend Ribassista", "desc": "SMA20 sotto SMA50"}); bear_count += 1

    if r is not None:
        if r < 30:   signals.append({"type": "bull",    "label": "RSI Oversold",   "desc": f"RSI a {r} — ipervenduto"});    bull_count += 2
        elif r > 70: signals.append({"type": "bear",    "label": "RSI Overbought", "desc": f"RSI a {r} — ipercomprato"});  bear_count += 2
        elif r > 50: signals.append({"type": "neutral", "label": "RSI Positivo",   "desc": f"RSI a {r} — momentum positivo"}); bull_count += 1

    if bb:
        if current < bb["lower"]:   signals.append({"type": "bull", "label": "Sotto Banda Inferiore", "desc": "Possibile rimbalzo"}); bull_count += 1
        elif current > bb["upper"]: signals.append({"type": "bear", "label": "Sopra Banda Superiore", "desc": "Possibile correzione"}); bear_count += 1

    if m is not None:
        if m > 0: signals.append({"type": "bull", "label": "MACD Positivo", "desc": f"MACD: +{m}"}); bull_count += 1
        else:     signals.append({"type": "bear", "label": "MACD Negativo", "desc": f"MACD: {m}"}); bear_count += 1

    if e20:
        if current > e20: signals.append({"type": "bull", "label": "Sopra EMA20", "desc": "Prezzo in zona di forza"}); bull_count += 1
        else:             signals.append({"type": "bear", "label": "Sotto EMA20", "desc": "Prezzo in zona di debolezza"}); bear_count += 1

    total = bull_count + bear_count
    score = round(bull_count / total * 100) if total > 0 else 50
    if score >= 70:   rec, rc = "ACQUISTO",  "bull"
    elif score >= 55: rec, rc = "ACCUMULO",  "bull-light"
    elif score <= 30: rec, rc = "VENDITA",   "bear"
    elif score <= 45: rec, rc = "RIDUZIONE", "bear-light"
    else:             rec, rc = "NEUTRO",    "neutral"

    return {"current": round(current, 4), "change1d": change1d, "change1m": change1m,
            "sma20": round(s20, 4) if s20 else None, "sma50": round(s50, 4) if s50 else None,
            "ema20": e20, "rsi": r, "macd": m, "bb": bb, "signals": signals,
            "score": score, "recommendation": rec, "recColor": rc,
            "bullCount": bull_count, "bearCount": bear_count}


@app.route("/api/stocks")
def get_all_stocks():
    cache, result, errors = load_cache(), [], []
    for ticker, info in TITOLI.items():
        cached = cache.get(ticker, {})
        if cache_valid(cached):
            prices = cached["prices"]
            print(f"[cache] {ticker}")
        else:
            try:
                print(f"[fetch] {ticker} ({info['yf_ticker']}) ...")
                prices = fetch_daily(info["yf_ticker"])
                cache[ticker] = {"prices": prices, "timestamp": datetime.now().isoformat()}
                save_cache(cache)
            except Exception as e:
                print(f"[error] {ticker}: {e}")
                errors.append({"ticker": ticker, "error": str(e)})
                prices = cached.get("prices")
                if not prices:
                    continue
        try:
            analysis = analyze(ticker, prices)
            result.append({"ticker": ticker, "name": info["name"], "category": info["category"],
                           "currency": "EUR", "prices": prices[-120:], **analysis})
        except Exception as e:
            errors.append({"ticker": ticker, "error": f"Analisi fallita: {e}"})
    return jsonify({"stocks": result, "errors": errors, "updated": datetime.now().isoformat()})


@app.route("/api/stock/<ticker>")
def get_stock(ticker):
    ticker = ticker.upper()
    if ticker not in TITOLI:
        return jsonify({"error": "Ticker non trovato"}), 404
    cache, info, cached = load_cache(), TITOLI[ticker], load_cache().get(ticker, {})
    if cache_valid(cached):
        prices = cached["prices"]
    else:
        try:
            prices = fetch_daily(info["yf_ticker"])
            cache[ticker] = {"prices": prices, "timestamp": datetime.now().isoformat()}
            save_cache(cache)
        except Exception as e:
            return jsonify({"error": str(e)}), 502
    return jsonify({"ticker": ticker, "name": info["name"], "category": info["category"],
                    "currency": "EUR", "prices": prices[-120:], **analyze(ticker, prices)})


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    return jsonify({"status": "cache svuotata"})


@app.route("/api/status")
def status():
    cache = load_cache()
    return jsonify({"status": "ok", "fonte": "Yahoo Finance", "cache": {
        t: {"cached": bool(cache.get(t, {}).get("prices")),
            "timestamp": cache.get(t, {}).get("timestamp", "—"),
            "valid": cache_valid(cache.get(t, {}))}
        for t in TITOLI
    }})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    print(f"\n🚀 FTSE MIB Agent Backend")
    print(f"   Fonte:  Yahoo Finance — gratuito, nessuna API key")
    print(f"   Porta:  {args.port}")
    print(f"   Cache:  {CACHE_TTL_MINUTES} min\n")
    app.run(port=args.port, debug=False)
