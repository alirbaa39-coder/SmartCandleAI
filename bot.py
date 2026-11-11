import os
import logging
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CHF": "CHF=X",
    "USD/CAD": "CAD=X",
    "NZD/USD": "NZDUSD=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/CHF": "EURCHF=X",
    "GBP/CHF": "GBPCHF=X",
    "AUD/JPY": "AUDJPY=X",
    "CAD/JPY": "CADJPY=X",
    "EUR/AUD": "EURAUD=X",
    "GBP/AUD": "GBPAUD=X",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smartcandle")

def pair_keyboard():
    rows, row = [], []
    for name in PAIRS:
        row.append(InlineKeyboardButton(name, callback_data=f"pair:{name}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔄 تحديث الأزواج", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def indicators(df):
    close = df["Close"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    rsi = 100 - (100 / (1 + rs))
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(rsi.iloc[-1]), float(macd.iloc[-1] - signal.iloc[-1])

def analyze(pair, ticker):
    df = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=False)
    if df is None or df.empty or len(df) < 40:
        raise ValueError("لم تصل بيانات كافية لهذا الزوج حالياً.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    # Ignore the currently forming candle.
    df = df.iloc[:-1]
    if len(df) < 35:
        raise ValueError("البيانات المتاحة غير كافية للتحليل.")
    ema9, ema21, rsi, macd_hist = indicators(df)
    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    score = 0
    score += 1 if ema9 > ema21 else -1
    score += 1 if last > ema9 else -1
    score += 1 if macd_hist > 0 else -1
    score += 1 if last > prev else -1

    if score >= 3 and 50 <= rsi <= 68:
        signal_text, icon = "شراء (CALL)", "🟢"
        reason = "الاتجاه القصير صاعد، والزخم إيجابي."
    elif score <= -3 and 32 <= rsi <= 50:
        signal_text, icon = "بيع (PUT)", "🔴"
        reason = "الاتجاه القصير هابط، والزخم سلبي."
    else:
        signal_text, icon = "انتظار", "🟡"
        reason = "الإشارات غير متوافقة بما يكفي؛ الأفضل عدم الدخول."
    stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"{icon} *نتيجة تحليل {pair} — إطار 5 دقائق*\n\n"
        f"*الإشارة:* {signal_text}\n"
        f"*قوة توافق المؤشرات:* {abs(score)}/4\n"
        f"*RSI:* {rsi:.1f}\n"
        f"*السعر المرجعي:* {last:.5f}\n"
        f"*السبب:* {reason}\n"
        f"*وقت التحليل:* {stamp}\n\n"
        "⚠️ هذه قراءة تعليمية آلية وليست ضماناً للربح أو توصية مؤكدة. "
        "قد تختلف الأسعار عن Pocket Option، وخصوصاً OTC. اختبرها تجريبياً أولاً."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 اطلب توصية", callback_data="menu")]
    ])
    await update.message.reply_text(
        "أهلاً بك في *Smart Candle AI* 👋\n"
        "اختر اطلب توصية، ثم اختر زوج العملات لتحليله على إطار 5 دقائق.",
        reply_markup=keyboard, parse_mode="Markdown"
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "اختر زوج العملات الذي تريد تحليله:",
        reply_markup=pair_keyboard()
    )

async def choose_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("جارٍ تحليل الزوج...")
    pair = query.data.split(":", 1)[1]
    ticker = PAIRS.get(pair)
    if not ticker:
        await query.edit_message_text("هذا الزوج غير متاح حالياً.", reply_markup=pair_keyboard())
        return
    try:
        result = analyze(pair, ticker)
        await query.edit_message_text(result, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 تحليل زوج آخر", callback_data="menu")]
            ]))
    except Exception as exc:
        log.exception("Analysis failed for %s", pair)
        await query.edit_message_text(
            f"تعذّر جلب بيانات {pair} حالياً. جرّب بعد قليل.\n"
            "ملاحظة: مصدر الأسعار قد يتوقف أو يتأخر أحياناً.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 اختيار زوج آخر", callback_data="menu")]
            ])
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اضغط /start ثم «اطلب توصية» واختر الزوج من القائمة.")

def main():
    if not TOKEN:
        raise SystemExit("ضع TELEGRAM_BOT_TOKEN في متغيرات البيئة أولاً.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(menu, pattern=r"^menu$"))
    app.add_handler(CallbackQueryHandler(choose_pair, pattern=r"^pair:"))
    log.info("Smart Candle AI is running.")
    app.run_polling()

if __name__ == "__main__":
    main()
