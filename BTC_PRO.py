#!/usr/bin/env python3
# ربات تحلیل ارز - نسخه ساده و دقیق برای پدر
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

COINS = {
    "🟠 بیت کوین": "BTCUSDT",
    "🔷 اتریوم": "ETHUSDT",
    "🟣 سولانا": "SOLUSDT",
    "🔵 ریپل": "XRPUSDT",
    "🟡 بایننس": "BNBUSDT",
    "⚪ کاردانو": "ADAUSDT",
    "🟢 دوج": "DOGEUSDT",
}

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
HIGHER_TF = {"5m": "15m", "15m": "1h", "1h": "4h", "4h": "1d", "1d": "1d"}

subscriptions = {}
lock = threading.Lock()


# ═══════════════ دریافت داده ═══════════════
def api(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Bot"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def candles(symbol, interval, limit=300):
    rows = api("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    now = int(time.time() * 1000)
    rows = [x for x in rows if int(x[6]) < now]  # فقط کندل بسته‌شده
    if len(rows) < 220:
        raise RuntimeError("داده کافی نیست")
    return {
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "close": [float(x[4]) for x in rows],
        "volume": [float(x[5]) for x in rows],
    }


# ═══════════════ اندیکاتورها ═══════════════
def ema(v, p):
    out = [None] * len(v)
    if len(v) < p:
        return out
    val = sum(v[:p]) / p
    out[p - 1] = val
    a = 2 / (p + 1)
    for i in range(p, len(v)):
        val = v[i] * a + val * (1 - a)
        out[i] = val
    return out


def rsi(v, p=14):
    out = [None] * len(v)
    if len(v) <= p:
        return out
    ch = [v[i] - v[i - 1] for i in range(1, len(v))]
    g = [max(x, 0) for x in ch]
    l = [max(-x, 0) for x in ch]
    ag, al = sum(g[:p]) / p, sum(l[:p]) / p

    def calc(g, l):
        if l == 0:
            return 100 if g else 50
        return 100 - 100 / (1 + g / l)

    out[p] = calc(ag, al)
    for i in range(p + 1, len(v)):
        ag = (ag * (p - 1) + g[i - 1]) / p
        al = (al * (p - 1) + l[i - 1]) / p
        out[i] = calc(ag, al)
    return out


def macd(v):
    f, s = ema(v, 12), ema(v, 26)
    line = [None] * len(v)
    for i in range(len(v)):
        if f[i] is not None and s[i] is not None:
            line[i] = f[i] - s[i]
    start = next((i for i, x in enumerate(line) if x is not None), len(line))
    sig = ema(line[start:], 9) if line[start:] else []
    hist = [None] * len(v)
    for j, x in enumerate(sig):
        i = start + j
        if x is not None and line[i] is not None:
            hist[i] = line[i] - x
    return hist


def dmi(data, p=14):
    h, l, c = data["high"], data["low"], data["close"]
    n = len(c)
    tr = [0.0] * n
    plus = [0.0] * n
    minus = [0.0] * n
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        plus[i] = up if up > dn and up > 0 else 0
        minus[i] = dn if dn > up and dn > 0 else 0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    st, sp, sm = sum(tr[1:p + 1]), sum(plus[1:p + 1]), sum(minus[1:p + 1])
    dx = []
    pdi = mdi = 0
    for i in range(p + 1, n):
        st = st - st / p + tr[i]
        sp = sp - sp / p + plus[i]
        sm = sm - sm / p + minus[i]
        if st == 0:
            continue
        pdi, mdi = 100 * sp / st, 100 * sm / st
        t = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / t if t else 0)
    if len(dx) < p:
        return 0, 0, 0
    adx = sum(dx[:p]) / p
    for x in dx[p:]:
        adx = (adx * (p - 1) + x) / p
    return pdi, mdi, adx


# ═══════════════ تحلیل اصلی ═══════════════
def analyze(data):
    c, h, l, v = data["close"], data["high"], data["low"], data["volume"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    rr = rsi(c)
    hist = macd(c)
    pdi, mdi, adx = dmi(data)
    i = -1
    price = c[-1]

    # امتیازدهی
    bull = bear = 0
    if price > e20[i]: bull += 2
    else: bear += 2
    if e20[i] > e50[i]: bull += 2
    else: bear += 2
    if e50[i] > e200[i]: bull += 2
    else: bear += 2
    if rr[i] > 55: bull += 2
    elif rr[i] < 45: bear += 2
    if hist[i] > 0 and hist[i] > hist[-2]: bull += 2
    elif hist[i] < 0 and hist[i] < hist[-2]: bear += 2
    if adx >= 18:
        if pdi > mdi: bull += 2
        elif mdi > pdi: bear += 2
    res = max(h[-21:-1])
    sup = min(l[-21:-1])
    if price > res: bull += 3
    if price < sup: bear += 3

    total = bull + bear
    score = (bull / total * 100) if total > 0 else 50

    # تأیید حجم
    avg_vol = sum(v[-11:-1]) / 10 if len(v) >= 11 else 0
    vol_ok = v[-1] > avg_vol * 1.05 if avg_vol else False

    # متن‌ها
    if adx < 20: trend = "بدون روند (رِنج)"
    elif adx < 25: trend = "در حال شکل‌گیری"
    elif adx < 40: trend = "روند قوی"
    else: trend = "روند خیلی قوی"

    if rr[i] < 30: rsi_txt = "اشباع فروش"
    elif rr[i] > 70: rsi_txt = "اشباع خرید"
    else: rsi_txt = "خنثی"

    if hist[i] > 0 and hist[i] > hist[-2]: macd_txt = "صعودی"
    elif hist[i] < 0 and hist[i] < hist[-2]: macd_txt = "نزولی"
    else: macd_txt = "کم‌جان"

    if score >= 65: status = "🟢 صعودی"
    elif score <= 35: status = "🔴 نزولی"
    else: status = "🟡 خنثی"

    # توصیه نهایی
    buy = score >= 65 and adx >= 20 and rr[i] < 70 and vol_ok and hist[i] > 0
    sell = score <= 35 and adx >= 20 and rr[i] > 30 and vol_ok and hist[i] < 0

    if buy:
        action = "🟢 خرید بزن"
        reason = "روند، مومنتوم و حجم همه تأیید کردن."
    elif sell:
        action = "🔴 فروش بزن"
        reason = "روند، مومنتوم و حجم همه تأیید کردن."
    else:
        action = "🟡 دست نگه دار"
        if score >= 65 or score <= 35:
            missing = []
            if not vol_ok: missing.append("حجم کم")
            if adx < 20: missing.append("روند ضعیف")
            reason = "چون " + " و ".join(missing) + " است، ریسک بالاست." if missing else "شرایط کامل نیست."
        else:
            reason = "بازار جهت مشخصی نداره، صبر کن."

    return {
        "price": price, "score": score, "status": status,
        "trend": trend, "rsi_txt": rsi_txt, "macd_txt": macd_txt,
        "rsi": rr[i], "adx": adx, "sup": sup, "res": res,
        "action": action, "reason": reason, "vol_ok": vol_ok,
    }


# ═══════════════ تلگرام ═══════════════
def send(msg, chat_id=None, keyboard=None):
    if not TOKEN:
        return
    target = chat_id or CHAT
    if not target:
        return
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    payload = {"chat_id": target, "text": msg}
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
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


# ═══════════════ کیبوردها ═══════════════
def coins_kb():
    rows = []
    items = list(COINS.keys())
    for i in range(0, len(items), 2):
        rows.append([{"text": x} for x in items[i:i + 2]])
    return {"keyboard": rows, "resize_keyboard": True}


def tf_kb():
    return {
        "keyboard": [
            [{"text": t} for t in TIMEFRAMES[:3]],
            [{"text": t} for t in TIMEFRAMES[3:]],
            [{"text": "📊 همه تایم‌فریم‌ها"}],
            [{"text": "🔙 بازگشت"}],
        ],
        "resize_keyboard": True,
    }


# ═══════════════ ساخت پیام ═══════════════
def analysis_text(coin, sym, tf, r, higher=None, higher_tf=None, auto=False):
    head = "🔔 تحلیل خودکار" if auto else "📊 تحلیل"
    t = f"{head} {coin} ({tf})\n"
    t += "─────────────\n"
    t += f"💰 قیمت: ${r['price']:,.4f}\n"
    t += f"📌 وضعیت: {r['status']} ({r['score']:.0f}/100)\n\n"
    t += f"📈 روند: {r['trend']}\n"
    t += f"🧠 روانشناسی: {r['rsi_txt']} (RSI {r['rsi']:.1f})\n"
    t += f"⚡ مومنتوم: {r['macd_txt']}\n"
    t += f"📊 حجم: {'تأیید ✅' if r['vol_ok'] else 'ضعیف ❌'}\n\n"
    t += f"🟢 حمایت: ${r['sup']:,.4f}\n"
    t += f"🔴 مقاومت: ${r['res']:,.4f}\n"

    if higher:
        t += "─────────────\n"
        t += f"🔭 تایم بالاتر ({higher_tf}): {higher['action']}\n"

    t += "─────────────\n"
    t += f"🎯 توصیه: {r['action']}\n"
    t += f"💡 {r['reason']}"
    return t


def do_analysis(chat_id, coin, sym, tf, auto=False):
    try:
        data = candles(sym, tf)
        r = analyze(data)
        higher = higher_tf = None
        htf = HIGHER_TF.get(tf)
        if htf and htf != tf:
            try:
                higher = analyze(candles(sym, htf))
                higher_tf = htf
            except Exception:
                pass
        send(analysis_text(coin, sym, tf, r, higher, higher_tf, auto), chat_id, tf_kb())
    except Exception as e:
        send(f"❌ خطا: {e}", chat_id, tf_kb())


def do_all_tf(chat_id, coin, sym):
    try:
        send(f"⏳ دارم {coin} رو در همه تایم‌فریم‌ها بررسی می‌کنم...", chat_id)
        lines = [f"📊 بررسی کامل {coin}\n─────────────"]
        buys = sells = 0
        for tf in TIMEFRAMES:
            try:
                r = analyze(candles(sym, tf))
                icon = "🟢" if "خرید" in r["action"] else "🔴" if "فروش" in r["action"] else "🟡"
                if "خرید" in r["action"]: buys += 1
                if "فروش" in r["action"]: sells += 1
                lines.append(f"{icon} {tf}: {r['action']} | {r['score']:.0f}/100")
            except Exception as e:
                lines.append(f"⚠️ {tf}: خطا")
            time.sleep(0.3)
        lines.append("─────────────")
        if buys >= 3:
            lines.append("✅ نتیجه: همه تایم‌فریم‌ها صعودی — فرصت خرید")
        elif sells >= 3:
            lines.append("✅ نتیجه: همه تایم‌فریم‌ها نزولی — فرصت فروش")
        else:
            lines.append("⚠️ نتیجه: تایم‌فریم‌ها با هم هماهنگ نیستن، احتیاط کن")
        send("\n".join(lines), chat_id, tf_kb())
    except Exception as e:
        send(f"❌ خطا: {e}", chat_id)


# ═══════════════ تایمر خودکار ═══════════════
def auto_timer():
    print("Auto-timer started (15 min)")
    while True:
        time.sleep(900)
        with lock:
            subs = list(subscriptions.items())
        for chat_id, sub in subs:
            try:
                do_analysis(chat_id, sub["coin"], COINS[sub["coin"]], sub["tf"], auto=True)
                time.sleep(1)
            except Exception as e:
                print("Auto error:", e)


# ═══════════════ حلقه اصلی ═══════════════
def main():
    print("Bot is running...")
    last_id = None
    threading.Thread(target=auto_timer, daemon=True).start()

    while True:
        try:
            updates = get_updates(last_id)
            if updates.get("ok"):
                for u in updates["result"]:
                    last_id = u["update_id"] + 1
                    if "message" not in u or "text" not in u["message"]:
                        continue
                    text = u["message"]["text"].strip()
                    chat_id = str(u["message"]["chat"]["id"])
                    if CHAT and chat_id != CHAT:
                        continue

                    if text in ["/start", "شروع", "استارت"]:
                        send(
                            "سلام 👋\n\n"
                            "این ربات بهت می‌گه کِی بخری و کِی بفروشی.\n\n"
                            "1️⃣ اول یه ارز انتخاب کن\n"
                            "2️⃣ بعد تایم‌فریم رو انتخاب کن\n\n"
                            "بعد از اون، هر ۱۵ دقیقه خودش تحلیل می‌فرسته 📩",
                            chat_id, coins_kb(),
                        )

                    elif text in COINS:
                        with lock:
                            prev = subscriptions.get(chat_id, {})
                            subscriptions[chat_id] = {"coin": text, "tf": prev.get("tf", "15m")}
                        send(f"✅ {text} انتخاب شد\n\nحالا تایم‌فریم رو بزن:", chat_id, tf_kb())

                    elif text in ["🔙 بازگشت", "بازگشت"]:
                        send("لیست ارزها:", chat_id, coins_kb())

                    elif text == "📊 همه تایم‌فریم‌ها":
                        with lock:
                            sub = subscriptions.get(chat_id)
                        if not sub:
                            send("اول یه ارز انتخاب کن:", chat_id, coins_kb())
                            continue
                        threading.Thread(
                            target=do_all_tf,
                            args=(chat_id, sub["coin"], COINS[sub["coin"]]),
                            daemon=True,
                        ).start()

                    elif text in TIMEFRAMES:
                        with lock:
                            sub = subscriptions.get(chat_id)
                            if sub:
                                sub["tf"] = text
                        if not sub:
                            send("اول یه ارز انتخاب کن:", chat_id, coins_kb())
                            continue
                        send(f"⏳ دارم {sub['coin']} ({text}) رو تحلیل می‌کنم...", chat_id)
                        do_analysis(chat_id, sub["coin"], COINS[sub["coin"]], text)
                        send(
                            f"⏰ باشه! از الان هر ۱۵ دقیقه تحلیل {sub['coin']} ({text}) رو برات می‌فرستم.",
                            chat_id, tf_kb(),
                        )

                    elif text in ["/stop", "توقف", "قطع"]:
                        with lock:
                            had = subscriptions.pop(chat_id, None)
                        send("🛑 ارسال خودکار قطع شد." if had else "چیزی برای قطع کردن نبود.", chat_id)

                    else:
                        send("از دکمه‌های زیر استفاده کن 👇", chat_id, coins_kb())
            time.sleep(1)
        except Exception as e:
            print("Error:", e)
            time.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ BOT_TOKEN تنظیم نشده!")
        sys.exit(1)
    main()
