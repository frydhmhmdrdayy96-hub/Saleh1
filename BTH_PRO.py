#!/usr/bin/env python3
# BTC PRO MULTI V21 - Multi-Coin + Auto Timer per User
import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse

BASE = "https://data-api.binance.vision"
TOKEN = os.getenv("BOT_TOKEN", "")
CHAT = os.getenv("ALLOWED_CHAT_ID", "") or os.getenv("CHAT_ID", "")
TIMEOUT = 20
AUTO_INTERVAL = 900  # 15 دقیقه

DEFAULT_TIMEFRAME = "15m"

COINS = {
    "🟠 بیت کوین": "BTCUSDT",
    "🔷 اتریوم": "ETHUSDT",
    "🟣 سولانا": "SOLUSDT",
    "🔵 ریپل": "XRPUSDT",
    "🟡 بایننس کوین": "BNBUSDT",
    "⚪ کاردانو": "ADAUSDT",
    "🟢 دوج کوین": "DOGEUSDT",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

# chat_id -> {"coin": "🟠 بیت کوین", "tf": "15m"}
subscriptions = {}
lock = threading.Lock()


# ─── API ───
def api(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "BTC-PRO-V21"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def candles(symbol, interval, limit=300):
    rows = api("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    now = int(time.time() * 1000)
    rows = [x for x in rows if int(x[6]) < now]
    if len(rows) < 220:
        raise RuntimeError("داده کافی نیست: " + interval)
    return {
        "time": [int(x[0]) for x in rows],
        "open": [float(x[1]) for x in rows],
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "close": [float(x[4]) for x in rows],
        "volume": [float(x[5]) for x in rows],
    }


# ─── اندیکاتورها ───
def ema(v, p):
    out = [None] * len(v)
    if len(v) < p:
        return out
    value = sum(v[:p]) / p
    out[p - 1] = value
    alpha = 2 / (p + 1)
    for i in range(p, len(v)):
        value = v[i] * alpha + value * (1 - alpha)
        out[i] = value
    return out


def rsi(v, p=14):
    out = [None] * len(v)
    if len(v) <= p:
        return out
    changes = [v[i] - v[i - 1] for i in range(1, len(v))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p

    def calc(g, l):
        if l == 0:
            return 100 if g else 50
        return 100 - 100 / (1 + g / l)

    out[p] = calc(ag, al)
    for i in range(p + 1, len(v)):
        ag = (ag * (p - 1) + gains[i - 1]) / p
        al = (al * (p - 1) + losses[i - 1]) / p
        out[i] = calc(ag, al)
    return out


def macd(v):
    f, s = ema(v, 12), ema(v, 26)
    line = [None] * len(v)
    for i in range(len(v)):
        if f[i] is not None and s[i] is not None:
            line[i] = f[i] - s[i]
    start = next((i for i, x in enumerate(line) if x is not None), len(line))
    valid = line[start:]
    sig = ema(valid, 9) if valid else []
    signal = [None] * len(v)
    hist = [None] * len(v)
    for j, x in enumerate(sig):
        i = start + j
        if x is not None and line[i] is not None:
            signal[i] = x
            hist[i] = line[i] - x
    return line, signal, hist


def dmi(data, p=14):
    h, l, c = data["high"], data["low"], data["close"]
    n = len(c)
    tr = [0.0] * n
    plus = [0.0] * n
    minus = [0.0] * n
    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus[i] = up if up > down and up > 0 else 0
        minus[i] = down if down > up and down > 0 else 0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    st = sum(tr[1:p + 1])
    sp = sum(plus[1:p + 1])
    sm = sum(minus[1:p + 1])
    dx = []
    last_pdi = last_mdi = 0
    for i in range(p + 1, n):
        st = st - st / p + tr[i]
        sp = sp - sp / p + plus[i]
        sm = sm - sm / p + minus[i]
        if st == 0:
            continue
        last_pdi = 100 * sp / st
        last_mdi = 100 * sm / st
        total = last_pdi + last_mdi
        dx.append(100 * abs(last_pdi - last_mdi) / total if total else 0)
    if len(dx) < p:
        return 0, 0, 0
    adx = sum(dx[:p]) / p
    for x in dx[p:]:
        adx = (adx * (p - 1) + x) / p
    return last_pdi, last_mdi, adx


def analyze(data):
    c, h, l, v = data["close"], data["high"], data["low"], data["volume"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    rr = rsi(c)
    _, _, mh = macd(c)
    pdi, mdi, adx_value = dmi(data)
    i = -1
    price = c[-1]

    bull = bear = 0
    if price > e20[i]: bull += 2
    else: bear += 2
    if e20[i] > e50[i]: bull += 2
    else: bear += 2
    if e50[i] > e200[i]: bull += 2
    else: bear += 2
    if rr[i] > 55: bull += 2
    elif rr[i] < 45: bear += 2
    if mh[i] > 0 and mh[i] > mh[-2]: bull += 2
    elif mh[i] < 0 and mh[i] < mh[-2]: bear += 2
    if adx_value >= 18:
        if pdi > mdi: bull += 2
        elif mdi > pdi: bear += 2

    resistance = max(h[-21:-1])
    support = min(l[-21:-1])
    if price > resistance: bull += 3
    if price < support: bear += 3

    typical = [(h[j] + l[j] + c[j]) / 3 for j in range(len(c) - 30, len(c))]
    volumes = v[-30:]
    tv = sum(volumes)
    vwap = sum(x * y for x, y in zip(typical, volumes)) / tv if tv else price
    if price > vwap: bull += 1
    elif price < vwap: bear += 1

    total = bull + bear
    normalized = (bull / total * 100) if total > 0 else 50

    if adx_value < 20: trend_text = "رِنج (بدون روند)"
    elif adx_value < 25: trend_text = "در حال شکل‌گیری"
    elif adx_value < 40: trend_text = "روند قوی"
    else: trend_text = "روند بسیار قوی"

    if rr[i] < 30: rsi_text = "اشباع فروش"
    elif rr[i] > 70: rsi_text = "اشباع خرید"
    else: rsi_text = "خنثی"

    if mh[i] > 0 and mh[i] > mh[-2]: macd_text = "صعودی (خریداران)"
    elif mh[i] < 0 and mh[i] < mh[-2]: macd_text = "نزولی (فروشندگان)"
    else: macd_text = "کم‌جان"

    if normalized >= 65: status = "🟢 صعودی"
    elif normalized <= 35: status = "🔴 نزولی"
    else: status = "🟡 خنثی"

    if normalized >= 65 and adx_value >= 20 and rr[i] < 70:
        action, action_desc = "🟢 خرید بزن", "شرایط صعودی تایید شد."
    elif normalized <= 35 and adx_value >= 20 and rr[i] > 30:
        action, action_desc = "🔴 فروش بزن", "شرایط نزولی تایید شد."
    else:
        action, action_desc = "🟡 معامله نکن", "شرایط برای ورود امن نیست، صبر کنید."

    return {
        "price": price, "trend_text": trend_text, "rsi_text": rsi_text,
        "macd_text": macd_text, "status": status, "support": support,
        "resistance": resistance, "action": action, "action_desc": action_desc,
        "rsi_value": rr[i], "adx_value": adx_value,
        "pdi": pdi, "mdi": mdi, "vwap": vwap, "normalized": normalized,
    }


# ─── تلگرام ───
def send_telegram(message, chat_id=None, reply_markup=None):
    if not TOKEN:
        return
    target = chat_id or CHAT
    if not target:
        return
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    payload = {"chat_id": target, "text": message}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data)
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception as e:
        print("Telegram error:", e)


def get_updates(offset=None):
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=TIMEOUT + 10) as r:
        return json.loads(r.read().decode())


# ─── کیبوردها ───
def coins_keyboard():
    rows = []
    items = list(COINS.keys())
    for i in range(0, len(items), 2):
        rows.append([{"text": x} for x in items[i:i + 2]])
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": False}


def timeframes_keyboard():
    return {
        "keyboard": [
            [{"text": t} for t in TIMEFRAMES[:3]],
            [{"text": t} for t in TIMEFRAMES[3:]],
            [{"text": "🔙 بازگشت به ارزها"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


# ─── تحلیل ───
def build_analysis_message(coin_name, symbol, timeframe, r, auto=False):
    head = "🔔 تحلیل خودکار" if auto else "📊 تحلیل"
    msg = f"{head} {coin_name} ({timeframe})\n"
    msg += f"نماد: `{symbol}`\n"
    msg += "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
    msg += f"💰 قیمت: ${r['price']:,.4f}\n"
    msg += f"📌 وضعیت: {r['status']}  (امتیاز: {r['normalized']:.0f}/100)\n\n"
    msg += f"🔹 روند بازار: {r['trend_text']}  (ADX={r['adx_value']:.1f})\n"
    msg += f"🔹 روانشناسی: {r['rsi_text']}  (RSI={r['rsi_value']:.1f})\n"
    msg += f"🔹 مومنتوم: {r['macd_text']}\n"
    msg += f"🔹 VWAP: ${r['vwap']:,.4f}\n"
    msg += f"🔹 DMI: +DI={r['pdi']:.1f} / -DI={r['mdi']:.1f}\n\n"
    msg += f"🟢 حمایت: ${r['support']:,.4f}\n"
    msg += f"🔴 مقاومت: ${r['resistance']:,.4f}\n"
    msg += "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
    msg += f"🎯 توصیه نهایی: {r['action']}\n"
    msg += f"_{r['action_desc']}_"
    return msg


def send_analysis(chat_id, coin_name, symbol, timeframe, auto=False):
    try:
        data = candles(symbol, timeframe)
        r = analyze(data)
        msg = build_analysis_message(coin_name, symbol, timeframe, r, auto=auto)
        send_telegram(msg, chat_id=chat_id, reply_markup=timeframes_keyboard())
    except Exception as e:
        send_telegram(f"❌ خطا در تحلیل {coin_name} ({timeframe}):\n{e}",
                      chat_id=chat_id, reply_markup=timeframes_keyboard())
        print("Analysis Error:", e)


# ─── تایمر خودکار ───
def auto_timer():
    print(f"Auto-timer started (every {AUTO_INTERVAL // 60} mins).")
    while True:
        time.sleep(AUTO_INTERVAL)
        with lock:
            subs = list(subscriptions.items())
        if not subs:
            continue
        print(f"Auto analysis for {len(subs)} user(s)...")
        for chat_id, sub in subs:
            try:
                send_analysis(chat_id, sub["coin"], COINS[sub["coin"]], sub["tf"], auto=True)
                time.sleep(1)  # جلوگیری از rate limit تلگرام
            except Exception as e:
                print("Auto error for", chat_id, e)


# ─── حلقه اصلی ───
def handle_messages():
    print("Bot is running...")
    last_update_id = None

    t = threading.Thread(target=auto_timer, daemon=True)
    t.start()

    while True:
        try:
            updates = get_updates(last_update_id)
            if updates.get("ok"):
                for update in updates["result"]:
                    last_update_id = update["update_id"] + 1
                    if "message" not in update or "text" not in update["message"]:
                        continue
                    text = update["message"]["text"].strip()
                    chat_id = str(update["message"]["chat"]["id"])

                    if CHAT and chat_id != CHAT:
                        continue

                    if text in ["/start", "استارت", "شروع"]:
                        send_telegram(
                            "🤖 ربات تحلیل چند‌ارزی (با ارسال خودکار)\n\n"
                            "۱️⃣ اول ارز را انتخاب کن\n"
                            "۲️⃣ بعد تایم‌فریم را انتخاب کن\n"
                            "⏰ از آن به بعد، هر ۱۵ دقیقه تحلیل خودکار می‌گیری.",
                            chat_id=chat_id, reply_markup=coins_keyboard(),
                        )

                    elif text in COINS:
                        # فقط ذخیره ارز، تایم‌فریم هنوز قبلی
                        with lock:
                            prev = subscriptions.get(chat_id, {})
                            subscriptions[chat_id] = {
                                "coin": text,
                                "tf": prev.get("tf", DEFAULT_TIMEFRAME),
                            }
                        send_telegram(
                            f"✅ ارز انتخاب شد: {text}\n"
                            f"نماد: `{COINS[text]}`\n\n"
                            "حالا تایم‌فریم را انتخاب کن:",
                            chat_id=chat_id, reply_markup=timeframes_keyboard(),
                        )

                    elif text in ["🔙 بازگشت به ارزها", "بازگشت", "/back"]:
                        send_telegram("🔙 لیست ارزها:",
                                      chat_id=chat_id, reply_markup=coins_keyboard())

                    elif text in TIMEFRAMES:
                        with lock:
                            sub = subscriptions.get(chat_id)
                            if not sub:
                                sub = None
                            if sub:
                                sub["tf"] = text

                        if not sub:
                            send_telegram("❗ اول یک ارز انتخاب کن:",
                                          chat_id=chat_id, reply_markup=coins_keyboard())
                            continue

                        coin_name = sub["coin"]
                        send_telegram(f"⏳ در حال تحلیل {coin_name} ({text})...", chat_id=chat_id)
                        send_analysis(chat_id, coin_name, COINS[coin_name], text)
                        send_telegram(
                            f"⏰ تنظیم شد: از این به بعد هر ۱۵ دقیقه تحلیل خودکار "
                            f"{coin_name} ({text}) را می‌فرستم.",
                            chat_id=chat_id, reply_markup=timeframes_keyboard(),
                        )

                    elif text in ["/stop", "توقف", "قطع"]:
                        with lock:
                            had = subscriptions.pop(chat_id, None)
                        if had:
                            send_telegram("🛑 ارسال خودکار متوقف شد.", chat_id=chat_id)
                        else:
                            send_telegram("الان عضوی نداری که متوقف بشه.", chat_id=chat_id)

                    elif text in ["/analyze", "تحلیل", "تحلیل کن"]:
                        with lock:
                            sub = subscriptions.get(chat_id)
                        if sub:
                            send_telegram(f"⏳ در حال تحلیل {sub['coin']} ({sub['tf']})...",
                                          chat_id=chat_id)
                            send_analysis(chat_id, sub["coin"], COINS[sub["coin"]], sub["tf"])
                        else:
                            send_telegram("اول یک ارز انتخاب کن:",
                                          chat_id=chat_id, reply_markup=coins_keyboard())

                    else:
                        send_telegram(
                            "لطفاً از دکمه‌ها استفاده کن.\nبرای شروع مجدد: /start",
                            chat_id=chat_id, reply_markup=coins_keyboard(),
                        )
            time.sleep(1)
        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        print("BOT_TOKEN is missing!")
        sys.exit(1)
    handle_messages()
