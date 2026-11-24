# -*- coding: utf-8 -*-
"""
SMC Control Panel + Gemini  (ملف واحد - لا يحتاج أي ملفات خارجية)
-----------------------------------------------------------------
التشغيل:  python smc_control_panel.py
المتطلبات: pip install MetaTrader5 pandas numpy requests   (tkinter مدمجة مع بايثون)

سير العمل:
 1) تفتح لوحة التحكم ثم تتصل بمنصة MT5 تلقائياً.
 2) زر "جلب البيانات الحية" يحلل الفريمات المحددة ويعرض النتائج في اللوحة.
 3) زر "إنشاء الملف وإرساله للمزوّد" ينشئ ملف .txt (الأوامر + البيانات) ويرسله إلى المزوّد المختار:
    Gemini أو Claude (عبر API) أو Claude Code مباشرة بدون API، ويمكنك إيقاف الطلب بزر ⏹ في أي لحظة.
 4) تظهر النتيجة مرتبة في اللوحة، مع إرسالها إلى Telegram (يدوي أو تلقائي). زر "مشاركة" لحفظ الملف أو إرساله بلوتوث.
 5) المستقبل الخارجي موجود في الكود لكنه معلّق (EXTERNAL_RECEIVER_ENABLED = False).
 6) الربط مع تطبيق الأندرويد (SMC Phone): محلي (نفس الواي فاي - اكتشاف تلقائي) أو Firebase، يختار التطبيق المتاح تلقائياً.
    رمز الربط يظهر في القسم 4 من اللوحة ويُدخل مرة واحدة في التطبيق.
"""
import os
import re
import math
import json
import time
import queue
import base64
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import requests

# --------------------------
# Config
# --------------------------
SCRIPT_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
SETTINGS_PATH = SCRIPT_DIR / "smc_panel_settings.json"   # يُنشأ تلقائياً (إعدادات اللوحة)
REQUESTS_DIR = SCRIPT_DIR / "gemini_requests"            # تُحفظ فيه ملفات txt المُرسلة

SYMBOL = "XAUUSD"
MIN_BARS = 300
VOL_BIN_COUNT = 40
HV_MULTIPLIER = 2.0
PIVOT_LENGTH = 30
PIVOT_LOOKBACK = 3
SLOPE_MULTIPLIER = 1.0
FIB_DEPTH = 100
DEVIATION_MULT = 3.0
ATR_PERIOD = 10
VWAP_WINDOW_BARS = 50
MAX_TICKS_FETCH = 100000
ADX_PERIOD = 14
D1_CANDLES_LIMIT = 400
DELTA_WINDOW_MIN = 15      # نافذة الدلتا/معدل التيكات "الحالي" بالدقائق (مقابل متوسط 60 دقيقة)

DEFAULT_DELTA_PCT_TRIGGER = 12.0
DEFAULT_TICK_RATE_MULT = 2.5
DEFAULT_VOLUME_SPIKE_MULT = 3.0
XAU_DELTA_PCT_TRIGGER = 20.0
XAU_TICK_RATE_MULT = 3.0
XAU_VOLUME_SPIKE_MULT = 4.0

EXTERNAL_RECEIVER_ENABLED = False   # مستقبل خارجي: معلّق مؤقتاً


# --------------------------
# مزوّدو التحليل (الاختيار من القائمة في اللوحة)
# --------------------------
PROV_GEMINI = "Gemini"
PROV_CLAUDE_API = "Claude (عبر API)"
PROV_CLAUDE_CLI = "Claude Code (مباشر بدون API)"
PROVIDERS = [PROV_GEMINI, PROV_CLAUDE_API, PROV_CLAUDE_CLI]

# أسماء "latest" تتحدث تلقائياً مع Google فلا تتعطل بتغيّر الإصدارات
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"
GEMINI_PREFERRED = ["gemini-flash-latest", "gemini-pro-latest", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
GEMINI_MODELS_FALLBACK = list(GEMINI_PREFERRED)
CLAUDE_DEFAULT_MODEL = "claude-sonnet-5-5"
CLAUDE_PREFERRED = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-sonnet-4-5", "claude-opus-5-5"]
CLAUDE_MODELS_FALLBACK = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4-5"]


SAUDI_TZ = timezone(timedelta(hours=3))
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

DEFAULT_PROMPTS_TEMPLATE = """أنت محلل فني محترف في {asset} وخبير في SMC وتدفق الأوامر.
المطلوب:
1. قم بتحليل البيانات الحية الموجودة أسفل هذا الملف وأعطني صفقة (شراء أو بيع أو لا صفقة) إن وجدت فرصة مناسبة.
2. حدّد: نقطة الدخول، وقف الخسارة، الهدف الأول والثاني والثالث، نسبة العائد/المخاطرة، ودرجة الثقة من 100.
3. اشرح سبب الصفقة بإيجاز مع توافق الفريمات وADX وVWAP وOrder Block والسيولة وفيبوناتشي وحالة الاختراق الكاذب.
4. اذكر شروط إلغاء الصفقة وأي تحذيرات.
5. إن لم تكن هناك فرصة واضحة فقل ذلك صراحة ولا تخترع صفقة.
6. اكتب الإجابة بالعربية وبتنسيق مرتب: عناوين، قوائم نقطية، وجدول مختصر للصفقة."""

def asset_label(symbol):
    """اسم الأصل داخل الأوامر: الذهب يُكتب (الذهب (الرمز)) وغيره يُكتب برمزه."""
    u = str(symbol or "").upper()
    return f"الذهب ({symbol})" if ("XAU" in u or "GOLD" in u) else str(symbol)

def default_prompts(symbol):
    return DEFAULT_PROMPTS_TEMPLATE.replace("{asset}", asset_label(symbol))

def swap_symbol_in_text(text, old, new):
    """يبدّل اسم الرمز القديم بالجديد في نص الأوامر (في مرور واحد حتى لا يتكرر الاستبدال)."""
    if not old or old == new:
        return text
    pats = sorted({asset_label(old), str(old)}, key=len, reverse=True)
    rx = re.compile("|".join(re.escape(p) for p in pats))
    return rx.sub(lambda mm: asset_label(new) if mm.group(0) == asset_label(old) else str(new), text)

PRESET_PROMPTS = [
    "حدّد أقرب مناطق الدعم والمقاومة وأهم مستويات السيولة.",
    "قيّم قوة الاتجاه على كل الفريمات باستخدام ADX وDI.",
    "ابحث عن اختراقات كاذبة أو فخاخ سيولة في البيانات.",
    "أعطني خطة سكالبينج قصيرة على M1/M5.",
    "أعطني خطة سوينغ على H1/H4.",
    "قيّم المخاطر وحجم المركز المناسب لحساب 1000 دولار.",
]

# --------------------------
# Logging (ملف + شاشة + سجل اللوحة)
# --------------------------
LOG_FILE = SCRIPT_DIR / "smc_panel.log"
logging.basicConfig(filename=str(LOG_FILE), filemode="a",
                    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
UI_LOG_Q = queue.Queue()

def _out(text):
    try:
        print(text)
    except Exception:
        pass
    UI_LOG_Q.put(str(text))

def info_ar(text):
    _out(text); logger.info(text)

def error_ar(text):
    _out(text); logger.error(text)

def exception_ar(text, exc=None):
    _out(text)
    logger.exception(text + (f" | Exception: {exc}" if exc is not None else ""))

def set_symbol(s):
    global SYMBOL
    SYMBOL = s

def get_thresholds():
    u = SYMBOL.upper()
    if 'XAU' in u or 'GOLD' in u:
        return {'delta_pct': XAU_DELTA_PCT_TRIGGER, 'tick_rate_mult': XAU_TICK_RATE_MULT, 'volume_mult': XAU_VOLUME_SPIKE_MULT}
    return {'delta_pct': DEFAULT_DELTA_PCT_TRIGGER, 'tick_rate_mult': DEFAULT_TICK_RATE_MULT, 'volume_mult': DEFAULT_VOLUME_SPIKE_MULT}


# ==========================================================
# Analysis core (من السكربت الأصلي)
# ==========================================================
def get_rates_tf(tf, count=1200, end_dt_utc=None):
    """
    جلب بيانات فريم tf. إذا end_dt_utc معرف (datetime aware بالـ UTC),
    سيتم استخدام mt5.copy_rates_from لجلب 'count' شمعات بحيث تكون الشمعة الأخيرة عند/قبل end_dt_utc.
    """
    try:
        if end_dt_utc is None:
            info_ar(f"⏳ جلب بيانات الفريم: {tf} (عدد الشموع: {count}) - بيانات فورية ...")
            rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
        else:
            info_ar(f"⏳ جلب بيانات الفريم: {tf} حتى التاريخ/الوقت UTC {end_dt_utc.isoformat()} (عدد الشموع: {count}) ...")
            rates = mt5.copy_rates_from(SYMBOL, tf, end_dt_utc, count)
        if rates is None:
            error_ar(f"⚠ لم يتم إرجاع بيانات من MT5 للفريم {tf} (rates is None).")
            return None
        if len(rates) < MIN_BARS:
            error_ar(f"⚠ عدد الشموع للفريم {tf} أقل من الحد الأدنى ({len(rates)} < {MIN_BARS}).")
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC')
        for c in ['open','high','low','close','tick_volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        info_ar(f"✅ تم جلب وتحضير بيانات الفريم {tf} بنجاح. عدد الشموع: {len(df)}")
        return df
    except Exception as e:
        exception_ar(f"❌ استثناء عند جلب البيانات للفريم {tf}.", e)
        return None

# --------------------------
# Basic indicators (+ ADX)
# --------------------------
def add_indicators(df):
    try:
        info_ar("🔢 حساب المؤشرات الأساسية (SMA, EMA, ATR, body, ADX)...")
        for p in [10,14,50,100,200]:
            df[f'SMA_{p}'] = df['close'].rolling(p, min_periods=1).mean()
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['body'] = (df['close'] - df['open']).abs()
        # ATR
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = (df['high'] - df['close'].shift(1)).abs()
        df['tr3'] = (df['low'] - df['close'].shift(1)).abs()
        df['TR'] = df[['tr1','tr2','tr3']].max(axis=1)
        df['ATR'] = df['TR'].rolling(ATR_PERIOD, min_periods=1).mean()

        # ADX (Wilder-style smoothing approximated with ewm alpha=1/period)
        # Calculate +DM and -DM
        df['up_move'] = df['high'].diff()
        df['down_move'] = -df['low'].diff()
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)

        # Smooth TR, plus_dm, minus_dm using Wilder smoothing approximation
        # (alpha = 1/period)
        alpha = 1.0 / float(ADX_PERIOD)
        # use ewm to approximate Wilder smoothing
        df['TR_smooth'] = df['TR'].ewm(alpha=alpha, adjust=False).mean()
        df['plus_dm_smooth'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean()
        df['minus_dm_smooth'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()

        # Calculate DI
        df['PLUS_DI_14'] = np.where(df['TR_smooth'] > 0, 100.0 * (df['plus_dm_smooth'] / df['TR_smooth']), 0.0)
        df['MINUS_DI_14'] = np.where(df['TR_smooth'] > 0, 100.0 * (df['minus_dm_smooth'] / df['TR_smooth']), 0.0)

        # DX and ADX
        df['DX_14'] = np.where((df['PLUS_DI_14'] + df['MINUS_DI_14']) > 0,
                                100.0 * (np.abs(df['PLUS_DI_14'] - df['MINUS_DI_14']) / (df['PLUS_DI_14'] + df['MINUS_DI_14'])),
                                0.0)
        df['ADX_14'] = df['DX_14'].ewm(alpha=alpha, adjust=False).mean()

        info_ar("✅ انتهى حساب المؤشرات.")
        return df
    except Exception as e:
        exception_ar("❌ خطأ أثناء حساب المؤشرات.", e)
        raise

# --------------------------
# Pivot / OB / Volume / Fib / Raid
# --------------------------
def pivothigh_series(df, length):
    try:
        highs = df['high'].values
        n = len(highs)
        ph = np.full(n, np.nan)
        for i in range(length, n-length):
            window = highs[i-length:i+length+1]
            if highs[i] == np.max(window):
                ph[i] = highs[i]
        return pd.Series(ph, index=df.index)
    except Exception as e:
        exception_ar("❌ خطأ في pivothigh_series.", e)
        raise

def pivotlow_series(df, length):
    try:
        lows = df['low'].values
        n = len(lows)
        pl = np.full(n, np.nan)
        for i in range(length, n-length):
            window = lows[i-length:i+length+1]
            if lows[i] == np.min(window):
                pl[i] = lows[i]
        return pd.Series(pl, index=df.index)
    except Exception as e:
        exception_ar("❌ خطأ في pivotlow_series.", e)
        raise

def collect_recent_pivots(df, length=PIVOT_LENGTH, max_count=PIVOT_LOOKBACK):
    try:
        ph_series = pivothigh_series(df, length).dropna()
        pl_series = pivotlow_series(df, length).dropna()
        ph_vals = list(ph_series.iloc[-max_count:]) if not ph_series.empty else []
        pl_vals = list(pl_series.iloc[-max_count:]) if not pl_series.empty else []
        ph_idx = list(ph_series.index[-max_count:]) if not ph_series.empty else []
        pl_idx = list(pl_series.index[-max_count:]) if not pl_series.empty else []
        return ph_vals, ph_idx, pl_vals, pl_idx
    except Exception as e:
        exception_ar("❌ استثناء في collect_recent_pivots.", e)
        return [], [], [], []

def last_swings(df):
    ph = pivothigh_series(df, PIVOT_LENGTH).dropna()
    pl = pivotlow_series(df, PIVOT_LENGTH).dropna()
    last_high = float(ph.iloc[-1]) if len(ph) >= 1 else float(df['high'].rolling(200).max().iloc[-1])
    last_low  = float(pl.iloc[-1]) if len(pl) >= 1 else float(df['low'].rolling(200).min().iloc[-1])
    prev_high = float(ph.iloc[-2]) if len(ph) >= 2 else None
    prev_low  = float(pl.iloc[-2]) if len(pl) >= 2 else None
    return last_high, last_low, prev_high, prev_low

def detect_structure(df):
    try:
        last_high, last_low, prev_high, prev_low = last_swings(df)
        curr = float(df['close'].iloc[-1])
        prev_close = float(df['close'].iloc[-2]) if len(df) >= 2 else curr
        structure = "Range"
        if curr > last_high:
            if prev_high is not None and last_high < prev_high and prev_close <= prev_high:
                structure = "CHoCH (Bullish)"
            else:
                structure = "BOS (Bullish)"
        elif curr < last_low:
            if prev_low is not None and last_low > prev_low and prev_close >= prev_low:
                structure = "CHoCH (Bearish)"
            else:
                structure = "BOS (Bearish)"
        return structure, last_high, last_low
    except Exception as e:
        exception_ar("❌ خطأ في detect_structure.", e)
        raise

def detect_order_block(df, lookback=600, body_factor=1.7, confirm_bars=3):
    try:
        d = df.reset_index(drop=True).copy()
        d['avg_body'] = d['body'].rolling(20, min_periods=5).mean().bfill()
        max_look = min(len(d)-confirm_bars-2, lookback)
        for i in range(len(d)-confirm_bars-2, len(d)-max_look-1, -1):
            # safety: prevent using i-1 if i==0
            if i <= 0:
                continue
            avg_b = d.at[i, 'avg_body']
            if avg_b <= 0 or math.isnan(avg_b):
                continue
            if d.at[i, 'body'] > avg_b * body_factor:
                is_bull = d.at[i, 'close'] > d.at[i, 'open']
                end_idx = i + confirm_bars
                if end_idx >= len(d):
                    continue
                net = d.at[end_idx, 'close'] - d.at[i, 'close']
                if is_bull and net > avg_b*0.6:
                    zl = float(d.at[i-1, 'low']); zh = float(d.at[i-1, 'high'])
                elif (not is_bull) and net < -avg_b*0.6:
                    zl = float(d.at[i-1, 'low']); zh = float(d.at[i-1, 'high'])
                else:
                    continue
                post = d.loc[i+1:, 'close']
                tested = post[(post >= zl) & (post <= zh)]
                status = "Tested" if not tested.empty else "Untested"
                zone_str = f"{'Bull' if is_bull else 'Bear'}_Zone[{round(zl,4)}-{round(zh,4)}]"
                info_ar(f"🔍 تم العثور على Order Block: {zone_str} (Status: {status})")
                return zone_str, i-1, status
        info_ar("ℹ️ لم يتم العثور على Order Block حديث.")
        return "None", None, None
    except Exception as e:
        exception_ar("❌ خطأ في detect_order_block.", e)
        raise

def volume_profile_poc_boxes(df, bins=VOL_BIN_COUNT, threshold_mult=HV_MULTIPLIER):
    try:
        prices = df['close'].values
        vols = df['tick_volume'].values.astype(float)
        if np.nansum(vols) == 0:
            info_ar("ℹ️ بيانات الحجم صفرية => لا يوجد POC.")
            return None, []
        hist, edges = np.histogram(prices, bins=bins, weights=vols)
        centers = (edges[:-1] + edges[1:]) / 2
        idx = int(np.nanargmax(hist))
        poc = float(centers[idx])
        meanv = float(np.nanmean(hist))
        hv_idx = np.where(hist > meanv * threshold_mult)[0]
        boxes = []
        if len(hv_idx) > 0:
            group = [hv_idx[0]]
            for k in hv_idx[1:]:
                if k == group[-1] + 1:
                    group.append(k)
                else:
                    lo = float(edges[group[0]]); hi = float(edges[group[-1]+1])
                    boxes.append((round(lo,4), round(hi,4)))
                    group = [k]
            lo = float(edges[group[0]]); hi = float(edges[group[-1]+1])
            boxes.append((round(lo,4), round(hi,4)))
        info_ar(f"✅ تم حساب POC = {round(poc,4)} ووجدت {len(boxes)} High-Volume Boxes.")
        return round(poc,4), boxes
    except Exception as e:
        exception_ar("❌ خطأ في volume_profile_poc_boxes.", e)
        raise

def auto_fib_levels(df):
    try:
        ph = pivothigh_series(df, PIVOT_LENGTH).dropna()
        pl = pivotlow_series(df, PIVOT_LENGTH).dropna()
        if ph.empty or pl.empty:
            max_p = df['high'].rolling(FIB_DEPTH).max().iloc[-1]
            min_p = df['low'].rolling(FIB_DEPTH).min().iloc[-1]
        else:
            last_high = ph.iloc[-1]; last_low = pl.iloc[-1]
            if last_high > last_low:
                max_p = last_high; min_p = last_low
            else:
                max_p = df['high'].rolling(FIB_DEPTH).max().iloc[-1]
                min_p = df['low'].rolling(FIB_DEPTH).min().iloc[-1]
        diff = max_p - min_p
        if diff == 0:
            info_ar("ℹ️ الفارق بين أعلى وأدنى = 0 => لا مستويات فيبوناتشي.")
            return {}
        levels = {
            "0.236": round(min_p + 0.236*diff, 4),
            "0.382": round(min_p + 0.382*diff, 4),
            "0.5": round(min_p + 0.5*diff, 4),
            "0.618": round(min_p + 0.618*diff, 4),
            "0.786": round(min_p + 0.786*diff, 4),
            "1.0": round(max_p, 4),
            "1.272": round(min_p + 1.272*diff, 4),
            "1.414": round(min_p + 1.414*diff, 4),
            "1.618": round(min_p + 1.618*diff, 4),
            "1.786": round(min_p + 1.786*diff, 4),
            "2.0": round(min_p + 2.0*diff, 4)
        }
        info_ar("✅ تم حساب مستويات فيبوناتشي تلقائية.")
        return levels
    except Exception as e:
        exception_ar("❌ خطأ في auto_fib_levels.", e)
        raise

def detect_liquidity_raid(df, lookback=30):
    try:
        h_target = float(df['high'].iloc[-lookback:-1].max())
        l_target = float(df['low'].iloc[-lookback:-1].min())
    except Exception as e:
        error_ar("⚠ لا يوجد بيانات كافية لحساب Raid targets.")
        return "Stable", None, None
    try:
        c_h = float(df['high'].iloc[-1]); c_c = float(df['close'].iloc[-1]); c_l = float(df['low'].iloc[-1])
        if c_h > h_target and c_c < h_target:
            info_ar("⚡ تم اكتشاف Raid High (Stop Hunt).")
            return "Raid High ⚡", h_target, l_target
        if c_l < l_target and c_c > l_target:
            info_ar("⚡ تم اكتشاف Raid Low (Stop Hunt).")
            return "Raid Low ⚡", h_target, l_target
        return "Stable", h_target, l_target
    except Exception as e:
        exception_ar("❌ خطأ أثناء كشف Raid.", e)
        return "Stable", None, None

# --------------------------
# VWAP (last N bars) & Delta Intent (last N bars)
# --------------------------
def compute_vwap_deviation_last_n(df, n_bars=VWAP_WINDOW_BARS):
    try:
        n = min(len(df), int(n_bars))
        if n <= 0:
            return {'vwap': None, 'last_price': float(df['close'].iloc[-1]), 'deviation_pct': None, 'session_volume': 0.0}
        window = df.iloc[-n:].copy()
        tp = (window['high'] + window['low'] + window['close']) / 3.0
        vol = window['tick_volume'].astype(float).replace(0, np.nan).fillna(0.0)
        num = (tp * vol).sum()
        den = vol.sum()
        if den == 0:
            return {'vwap': None, 'last_price': float(df['close'].iloc[-1]), 'deviation_pct': None, 'session_volume': 0.0}
        vwap = float(num / den)
        last_price = float(df['close'].iloc[-1])
        deviation_pct = (last_price - vwap) / vwap * 100.0
        return {'vwap': vwap, 'last_price': last_price, 'deviation_pct': deviation_pct, 'session_volume': den}
    except Exception as e:
        exception_ar("❌ استثناء أثناء حساب VWAP (آخر N شموع).", e)
        return {'vwap': None, 'last_price': float(df['close'].iloc[-1]), 'deviation_pct': None, 'session_volume': 0.0}

# --------------------------
# New: tick rate & session start & signal logic
# --------------------------
def detect_volume_spike(df, lookback_bars=5, mult=DEFAULT_VOLUME_SPIKE_MULT):
    try:
        if len(df) < lookback_bars + 1:
            return False, None, None
        last_vol = float(df['tick_volume'].iloc[-1])
        avg_vol = float(df['tick_volume'].iloc[-(lookback_bars+1):-1].mean())
        if avg_vol == 0:
            return False, last_vol, avg_vol
        is_spike = last_vol >= (mult * avg_vol)
        return is_spike, last_vol, avg_vol
    except Exception as e:
        exception_ar("⚠ خطأ في detect_volume_spike.", e)
        return False, None, None

def compute_signal_for_tf(symbol, df, ob_zone, ob_status, vwap_info, delta_info, tick_rates, is_volume_spike, thresholds):
    try:
        score = 0.0

        delta_pct = delta_info.get('delta_pct', 0.0)
        vwap_dev = vwap_info.get('deviation_pct') if vwap_info is not None else 0.0

        tick_rate_now = tick_rates.get('tick_rate_now', 0.0)
        avg_tick_rate = tick_rates.get('avg_tick_rate', 0.0)
        tick_rate_condition = False
        if avg_tick_rate > 0:
            tick_rate_condition = tick_rate_now >= (thresholds['tick_rate_mult'] * avg_tick_rate)

        vol_cond = bool(is_volume_spike)
        ob_cond = (ob_zone is not None and ob_zone != "None" and (ob_status == "Tested"))
        delta_cond = abs(delta_pct) >= thresholds['delta_pct']

        vwap_dir_cond = False
        if delta_pct > 0 and vwap_dev is not None and vwap_dev > 0:
            vwap_dir_cond = True
        if delta_pct < 0 and vwap_dev is not None and vwap_dev < 0:
            vwap_dir_cond = True

        weights = {'delta': 35, 'vwap_dir': 20, 'tick_rate': 15, 'volume_spike': 15, 'order_block': 15}
        if delta_cond: score += weights['delta']
        if vwap_dir_cond: score += weights['vwap_dir']
        if tick_rate_condition: score += weights['tick_rate']
        if vol_cond: score += weights['volume_spike']
        if ob_cond: score += weights['order_block']

        direction = None
        if delta_cond and vwap_dir_cond:
            direction = 'Long' if delta_pct > 0 else 'Short'
        else:
            satisfied = sum([delta_cond, vwap_dir_cond, tick_rate_condition, vol_cond, ob_cond])
            if satisfied >= 3:
                direction = 'Long' if delta_pct > 0 else 'Short'
            else:
                direction = None

        score = min(max(score, 0.0), 100.0)
        checks = {
            'delta_pct': delta_pct,
            'vwap_dev': vwap_dev,
            'tick_rate_now': tick_rate_now,
            'avg_tick_rate': avg_tick_rate,
            'tick_rate_condition': tick_rate_condition,
            'volume_spike': vol_cond,
            'order_block_tested': ob_cond
        }
        return direction, int(score), checks
    except Exception as e:
        exception_ar("❌ خطأ في compute_signal_for_tf.", e)
        return None, 0, {}

# --------------------------
# False Breakout detection function (تم طلبها مدمجة)
# --------------------------
def detect_false_breakout(df, level_price, direction, delta_info, tick_rate_info, vwap_info, thresholds,
                          lookahead_bars=3, retest_bars=5, wick_factor=1.2, atr_multiplier_noise=0.25):
    """
    يفحص الأحداث التالية بعد حدوث اختراق محتمل عند level_price في DataFrame df:
    - direction: 'Long' أو 'Short' (اتجاه الاختراق المزعوم)
    - delta_info: dict من compute_delta_intent_last_n
    - tick_rate_info: dict من compute_tick_rate_and_avg
    - vwap_info: dict من compute_vwap_deviation_last_n
    - thresholds: dict يحتوي keys: 'delta_pct', 'tick_rate_mult', 'volume_mult'
    إرجاع: dict {
        'is_false': bool,
        'reason': str (مختصر),
        'score': int (0-100، كل شرط يزيد الدرجة للثقة أنه اختراق حقيقي),
        'details': {...}
    }
    """
    try:
        res = {'is_false': False, 'reason': None, 'score': 0, 'details': {}}
        if df is None or len(df) < 3:
            res['is_false'] = False
            res['reason'] = 'insufficient_data'
            return res

        # قيم أساسية
        last_close = float(df['close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1]) if 'ATR' in df.columns and not pd.isna(df['ATR'].iloc[-1]) else None
        if atr is None:
            # fallback: استخدام متوسط نطاق بسيط
            atr = float((df['high'] - df['low']).rolling(5, min_periods=1).mean().iloc[-1])

        # 1) هل حدث اختراق "ميت" ضوضائي (صغير جداً مقارنة بالـ ATR)؟
        movement = abs(last_close - level_price)
        if atr > 0 and movement < (atr * atr_multiplier_noise):
            res['is_false'] = True
            res['reason'] = 'noise_vs_ATR'
            res['details']['movement'] = movement
            res['details']['atr'] = atr
            return res  # ضوضاء => false breakout

        # 2) Quick reversal: خلال lookahead_bars السعر عاد داخل النطاق/فشل الاغلاق
        looked = df.iloc[-(lookahead_bars+1):].copy()  # آخر N+1 شموع تشمل الشمعة الاختراق (إن وُجدت)
        # نبحث عن إغلاقات تعيد السعر داخل مستوى الاختراق
        reversed_inside = False
        for idx in range(1, len(looked)):
            c = float(looked['close'].iloc[idx])
            if direction == 'Long' and c <= level_price:
                reversed_inside = True
                rev_idx = idx
                break
            if direction == 'Short' and c >= level_price:
                reversed_inside = True
                rev_idx = idx
                break
        if reversed_inside:
            res['is_false'] = True
            res['reason'] = 'quick_reversal'
            res['details']['reversal_index_from_end'] = rev_idx
            return res

        # 3) Wick rejection: وجود ظل طويل يعيد السعر داخل النطاق
        # نحسب max wick نسبةً إلى ATR خلال lookahead_bars
        max_wick = 0.0
        for i in range(1, min(lookahead_bars+1, len(looked))):
            o = float(looked['open'].iloc[i]); h = float(looked['high'].iloc[i]); l = float(looked['low'].iloc[i]); c = float(looked['close'].iloc[i])
            if direction == 'Long':
                wick = max(0.0, h - max(c, o))
                rejection = max(0.0, max(c, o) - l)
            else:
                wick = max(0.0, min(c, o) - l)
                rejection = max(0.0, h - min(c, o))
            max_wick = max(max_wick, wick, rejection)
        if atr is not None and max_wick >= (wick_factor * atr):
            res['is_false'] = True
            res['reason'] = 'wick_rejection'
            res['details']['max_wick'] = max_wick
            res['details']['atr'] = atr
            return res

        # 4) Volume / Tick confirmation
        ticks_now = tick_rate_info.get('tick_rate_now', 0.0)
        avg_tick = tick_rate_info.get('avg_tick_rate', 0.0)
        tick_cond = (avg_tick > 0 and ticks_now >= thresholds.get('tick_rate_mult', 2.0) * avg_tick)
        # volume: احصل على آخر حجم وavg من df إن متاح
        last_vol = float(df['tick_volume'].iloc[-1]) if 'tick_volume' in df.columns else 0.0
        avg_vol = float(df['tick_volume'].iloc[-6:-1].mean()) if len(df) >= 6 else last_vol
        vol_cond = (avg_vol > 0 and last_vol >= thresholds.get('volume_mult', 3.0) * avg_vol)

        # delta sign
        delta_pct = delta_info.get('delta_pct', 0.0)
        delta_dir_cond = (delta_pct > 0 and direction == 'Long') or (delta_pct < 0 and direction == 'Short')

        # إذا لم تتحقق أي من شروط التأكيد الحجم/تيكات/دلتا => شك كبير بأنه False
        confirm_count = sum([tick_cond, vol_cond, delta_dir_cond])
        res['details'].update({'tick_cond': tick_cond, 'vol_cond': vol_cond, 'delta_dir_cond': delta_dir_cond, 'confirm_count': confirm_count})

        # عتبة: إذا لا يوجد على الأقل اثنين من الثلاثة => علم False (يمكن تعديل بحسب الفريم)
        if confirm_count < 2:
            res['is_false'] = True
            res['reason'] = 'lack_of_confirmation'
            return res

        # 5) Failed retest: إذا حصلت إعادة اختبار للمستوى خلال retest_bars وتم رفضه (close مخالف) => False
        if len(df) >= retest_bars + 1:
            recent = df.iloc[-retest_bars:].copy()
            failed_retest = False
            for i in range(len(recent)):
                rc = float(recent['close'].iloc[i]); rh = float(recent['high'].iloc[i]); rl = float(recent['low'].iloc[i])
                if direction == 'Long':
                    if rl <= level_price and rc <= level_price:
                        failed_retest = True
                        break
                else:
                    if rh >= level_price and rc >= level_price:
                        failed_retest = True
                        break
            if failed_retest:
                res['is_false'] = True
                res['reason'] = 'failed_retest'
                return res

        # إذا وصلنا هنا فهناك تأكيد معقول => نزيد score بالإيجابيات
        score = 0
        score += 30 if tick_cond else 0
        score += 30 if vol_cond else 0
        score += 30 if delta_dir_cond else 0
        # تضامن VWAP: إذا السعر على نفس اتجاه VWAP dev
        vwap_dev = vwap_info.get('deviation_pct') if vwap_info else 0.0
        if (direction == 'Long' and vwap_dev and vwap_dev > 0) or (direction == 'Short' and vwap_dev and vwap_dev < 0):
            score += 10
        score = min(100, int(score))
        res['score'] = score
        res['is_false'] = False
        res['reason'] = 'confirmed_by_checks'
        return res
    except Exception as e:
        exception_ar("⚠ استثناء داخل detect_false_breakout.", e)
        return {'is_false': False, 'reason': 'error', 'score': 0, 'details': {'exception': str(e)}}


# ==========================================================
# Overrides / new logic (تصحيحات على النسخة الأصلية)
# ==========================================================
_TICK_CACHE = {"key": None, "ts": 0.0, "val": None}

def _recent_ticks(symbol, minutes=60, max_ticks=MAX_TICKS_FETCH):
    """يجلب تيكات آخر N دقيقة (مع كاش 15 ثانية حتى لا تتكرر الجلبات لكل فريم)."""
    key = (symbol, minutes)
    if _TICK_CACHE["key"] == key and time.time() - _TICK_CACHE["ts"] < 15:
        return _TICK_CACHE["val"]
    t = mt5.symbol_info_tick(symbol)
    end = datetime.fromtimestamp(t.time, tz=timezone.utc) if t is not None else datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
    if ticks is not None and len(ticks) > max_ticks:
        ticks = ticks[-max_ticks:]
    _TICK_CACHE.update({"key": key, "ts": time.time(), "val": ticks})
    return ticks

def _delta_from_ticks(arr):
    """الدلتا من تغير سعر المنتصف (bid+ask)/2؛ لأن last وvolume فارغان غالباً في الذهب CFD."""
    if arr is None or len(arr) < 2:
        return {'delta': 0.0, 'delta_abs': 0.0, 'delta_pct': 0.0, 'ticks': 0 if arr is None else len(arr)}
    mid = (arr['bid'].astype(float) + arr['ask'].astype(float)) / 2.0
    sign = np.sign(np.diff(mid))
    vol = arr['volume'][1:].astype(float)
    w = np.where(vol > 0, vol, 1.0)
    delta = float((sign * w).sum())
    total = float(w.sum())
    return {'delta': delta, 'delta_abs': abs(delta),
            'delta_pct': (delta / total * 100.0) if total > 0 else 0.0, 'ticks': int(len(arr))}

def compute_tick_rate_and_avg(symbol, df=None, window_minutes=60, max_ticks=MAX_TICKS_FETCH):
    empty = {'delta': 0.0, 'delta_abs': 0.0, 'delta_pct': 0.0, 'ticks': 0}
    try:
        ticks = _recent_ticks(symbol, window_minutes, max_ticks)
        if ticks is None or len(ticks) == 0:
            return {'tick_rate_now': 0.0, 'avg_tick_rate': 0.0, 'ticks_now': 0, 'ticks_hist': 0, 'delta_info': empty}
        avg_rate = len(ticks) / float(window_minutes)
        cutoff = int(ticks['time_msc'][-1]) - DELTA_WINDOW_MIN * 60 * 1000
        recent = ticks[ticks['time_msc'] >= cutoff]
        delta_info = _delta_from_ticks(recent)
        return {'tick_rate_now': len(recent) / float(DELTA_WINDOW_MIN), 'avg_tick_rate': avg_rate,
                'ticks_now': len(recent), 'ticks_hist': len(ticks), 'delta_info': delta_info}
    except Exception as e:
        exception_ar("❌ خطأ أثناء حساب tick rates/delta.", e)
        return {'tick_rate_now': 0.0, 'avg_tick_rate': 0.0, 'ticks_now': 0, 'ticks_hist': 0, 'delta_info': empty}

def detect_false_breakout_safe(df, level_price, direction, **kw):
    """يفحص الاختراق الكاذب فقط إذا حدثت محاولة اختراق فعلية للمستوى خلال آخر 4 شموع."""
    look = df.iloc[-4:]
    attempted = bool((look['high'] > level_price).any()) if direction == 'Long' else bool((look['low'] < level_price).any())
    if not attempted:
        return {'is_false': False, 'reason': 'no_breakout_attempt', 'score': 0, 'details': {}}
    return detect_false_breakout(df, level_price, direction, **kw)

def _r(x, n=3):
    try:
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)
    except Exception:
        return None

def analyze_timeframe(name, tf):
    """تحليل فريم واحد وإرجاع حقول مرتبة + آخر 8 شموع."""
    try:
        df = get_rates_tf(tf, count=D1_CANDLES_LIMIT if name == "D1" else 1200)
        if df is None:
            return None
        df = add_indicators(df)
        th = get_thresholds()
        price = float(df['close'].iloc[-1])

        window = max(10, PIVOT_LENGTH * 2)
        slope = float(np.polyfit(np.arange(window), df['close'].values[-window:], 1)[0]) * SLOPE_MULTIPLIER
        structure, last_h, last_l = detect_structure(df)
        ob_zone, _, ob_status = detect_order_block(df, lookback=600, body_factor=1.7, confirm_bars=3)
        raid, raid_h, raid_l = detect_liquidity_raid(df, lookback=30)
        poc, hv_boxes = volume_profile_poc_boxes(df, bins=VOL_BIN_COUNT, threshold_mult=HV_MULTIPLIER)
        fibs = auto_fib_levels(df)
        ph_vals, _, pl_vals, _ = collect_recent_pivots(df, length=PIVOT_LENGTH, max_count=PIVOT_LOOKBACK)
        vwap = compute_vwap_deviation_last_n(df, n_bars=VWAP_WINDOW_BARS)
        tr = compute_tick_rate_and_avg(SYMBOL, df, window_minutes=60)
        delta = tr['delta_info']
        # طفرة الحجم على الشموع المكتملة فقط (الأخيرة غير مكتملة)
        spike, last_vol, avg_vol = detect_volume_spike(df.iloc[:-1], lookback_bars=5, mult=th['volume_mult'])
        session_start = bool(tr['avg_tick_rate'] > 0 and tr['tick_rate_now'] >= th['tick_rate_mult'] * tr['avg_tick_rate'] and spike)
        direction, score, checks = compute_signal_for_tf(SYMBOL, df, ob_zone, ob_status, vwap, delta, tr, spike, th)

        kw = dict(delta_info=delta, tick_rate_info=tr, vwap_info=vwap, thresholds=th,
                  lookahead_bars=3, retest_bars=5, wick_factor=1.2, atr_multiplier_noise=0.25)
        fb_long = detect_false_breakout_safe(df, last_h, 'Long', **kw) if last_h is not None else {'is_false': False, 'reason': 'no_level', 'score': 0}
        fb_short = detect_false_breakout_safe(df, last_l, 'Short', **kw) if last_l is not None else {'is_false': False, 'reason': 'no_level', 'score': 0}

        last = df.iloc[-1]
        fields = {
            "سعر آخر شمعة (Close)": _r(price),
            "وقت آخر شمعة (وقت الخادم)": df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M'),
            "الهيكل": structure,
            "آخر Swing High": _r(last_h), "آخر Swing Low": _r(last_l),
            "آخر قمم Pivot": [_r(x) for x in ph_vals], "آخر قيعان Pivot": [_r(x) for x in pl_vals],
            "Order Block": f"{ob_zone} ({ob_status})",
            "Raid": raid, "مرجع Raid علوي / سفلي": f"{_r(raid_h)} / {_r(raid_l)}",
            "POC": poc, "مناطق الحجم العالي": hv_boxes,
            "ATR": _r(last['ATR']), "الانحدار (Slope)": _r(slope, 5),
            "SMA 10/50/100/200": f"{_r(last['SMA_10'])} / {_r(last['SMA_50'])} / {_r(last['SMA_100'])} / {_r(last['SMA_200'])}",
            "EMA200": _r(last['EMA_200']),
            "ADX(14)": _r(last['ADX_14'], 2), "+DI": _r(last['PLUS_DI_14'], 2), "-DI": _r(last['MINUS_DI_14'], 2),
            "VWAP (آخر 50 شمعة)": _r(vwap.get('vwap')), "انحراف VWAP %": _r(vwap.get('deviation_pct'), 4),
            f"Delta % (آخر {DELTA_WINDOW_MIN}د)": _r(delta.get('delta_pct'), 2),
            "TickRate الحالي/دقيقة": _r(tr['tick_rate_now'], 1), "متوسط TickRate/دقيقة (60د)": _r(tr['avg_tick_rate'], 1),
            "حجم آخر شمعة مكتملة / المتوسط": f"{_r(last_vol, 0)} / {_r(avg_vol, 0)}", "طفرة حجم": bool(spike),
            "نشاط مفاجئ (SessionStart)": session_start,
            "إشارة النظام": f"{direction or '-'} (ثقة {score}/100)",
            "فيبوناتشي": ", ".join(f"{k}={v}" for k, v in fibs.items()) if fibs else "-",
            "اختراق كاذب Long": f"{fb_long['is_false']} ({fb_long['reason']}, score {fb_long.get('score', 0)})",
            "اختراق كاذب Short": f"{fb_short['is_false']} ({fb_short['reason']}, score {fb_short.get('score', 0)})",
        }
        candles = [f"  {t:%m-%d %H:%M} | O {o:.2f} H {h:.2f} L {l:.2f} C {c:.2f} | V {int(v)}"
                   for t, o, h, l, c, v in df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].tail(8).itertuples(index=False)]
        return {"TimeFrame": name, "fields": fields, "candles": candles}
    except Exception as e:
        exception_ar(f"❌ فشل تحليل الفريم {name}.", e)
        return None

def get_current_price(symbol):
    """السعر الحالي الحي (آخر تيك) لحظة الجلب: Bid/Ask/Spread ووقت التيك."""
    try:
        mt5.symbol_select(symbol, True)
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        bid, ask = float(t.bid), float(t.ask)
        if bid <= 0 and ask <= 0:
            last = float(getattr(t, "last", 0) or 0)
            if last <= 0:
                return None
            bid = ask = last
        elif bid <= 0:
            bid = ask
        elif ask <= 0:
            ask = bid
        si = mt5.symbol_info(symbol)
        digits = int(si.digits) if si is not None else 2
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0, "spread": ask - bid, "digits": digits,
                "tick_time": datetime.fromtimestamp(int(t.time), tz=timezone.utc),
                "captured": datetime.now(SAUDI_TZ)}
    except Exception as e:
        exception_ar("⚠ تعذر جلب السعر الحالي.", e)
        return None

def fmt_price(price, key="bid"):
    return f"{price[key]:.{price['digits']}f}"

def rows_to_text(rows, symbol, price=None, fetch_time=None):
    now = (fetch_time or datetime.now(SAUDI_TZ)).strftime('%d/%m/%Y %H:%M:%S')
    out = [f"الرمز: {symbol}", f"وقت الجلب (الرياض): {now}"]
    out.append("=" * 50)
    if price:
        out.append(f"💰 السعر الحالي الآن: {fmt_price(price)}  (Bid) — هذا هو السعر الحالي الحي لحظة جلب البيانات")
        out.append(f"   Bid: {fmt_price(price)} | Ask: {fmt_price(price, 'ask')} | Spread: {price['spread']:.{price['digits']}f}")
        out.append(f"   وقت التيك (وقت خادم المنصة): {price['tick_time']:%Y-%m-%d %H:%M:%S} | "
                   f"وقت الجلب (الرياض): {price['captured']:%H:%M:%S}")
    else:
        out.append("⚠ تعذّر جلب السعر الحالي (لا يوجد تيك من المنصة — قد يكون السوق مغلقاً).")
    out.append("=" * 50)
    out += ["ملاحظة: الشمعة الأخيرة في كل فريم قد تكون غير مكتملة، و'سعر آخر شمعة' هو إغلاق الشمعة الجارية وليس بالضرورة السعر الحالي.",
            f"ملاحظة: Delta وTickRate محسوبان من تيكات آخر {DELTA_WINDOW_MIN} دقيقة وهما متطابقان في كل الفريمات.", ""]
    for r in rows:
        out.append("-" * 50)
        out.append(f"## الفريم {r['TimeFrame']}")
        for k, v in r['fields'].items():
            out.append(f"{k}: {v}")
        out.append("آخر 8 شموع:")
        out.extend(r['candles'])
        out.append("")
    return "\n".join(out)

def build_request_file(prompts, data_text, symbol):
    REQUESTS_DIR.mkdir(exist_ok=True)
    path = REQUESTS_DIR / f"SMC_{symbol}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    content = (prompts.strip() + "\n\n" + "=" * 60 + "\nالبيانات المجلوبة (حية من MT5)\n" + "=" * 60 + "\n" + data_text)
    path.write_text(content, encoding="utf-8")
    return path

# --------------------------
# Gemini / Telegram / External
# --------------------------
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
CLAUDE_BASE = "https://api.anthropic.com/v1"
CLAUDE_API_VERSION = "2023-06-01"
GEMINI_EXCLUDE = re.compile(r'embed|tts|image|live|audio|aqa|robot|computer|veo|imagen|deep-research|learnlm', re.I)
CLI_PROMPT = ("Read the attached file content (provided via stdin) and follow the instructions inside it "
              "exactly. Write the whole answer in Arabic.")


class Cancelled(Exception):
    """يُرفع عند ضغط زر الإيقاف."""


def _kill_process_tree(p):
    """يوقف العملية وكل عملياتها الفرعية (ويندوز: taskkill /T، غيره: مجموعة العمليات)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


class CancelToken:
    """رمز إلغاء: زر الإيقاف يستدعي cancel() فينتهي الانتظار فوراً بدون انتظار رد المزوّد."""
    def __init__(self):
        self.event = threading.Event()
        self.proc = None

    def cancel(self):
        self.event.set()
        p = self.proc
        if p is not None:
            _kill_process_tree(p)

    def is_set(self):
        return self.event.is_set()

    def check(self):
        if self.event.is_set():
            raise Cancelled()

    def sleep(self, sec):
        if self.event.wait(sec):
            raise Cancelled()


def http_call(cancel, method, url, **kw):
    """طلب HTTP قابل للإلغاء: يعمل في خيط جانبي، وإذا ضغطت إيقاف نتجاهل الرد ونرجع فوراً."""
    box = {}

    def run():
        try:
            box["r"] = requests.request(method, url, **kw)
        except Exception as e:
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.2)
        cancel.check()
    cancel.check()
    if "e" in box:
        raise box["e"]
    return box["r"]


def _api_error_text(r):
    try:
        js = r.json()
        err = js.get("error") if isinstance(js, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:400]
        return str(js)[:400]
    except Exception:
        return (r.text or "")[:400]


def _run_models(first_model, send_fn, list_fn, preferred, cancel, label):
    """
    المحرك المشترك: يجرّب الموديل المختار، وعند فشله (موديل غير موجود/غير مدعوم) يجلب قائمة الموديلات
    المتاحة فعلاً من المزوّد ويجرّب البدائل تلقائياً. الأخطاء المؤقتة (ضغط/شبكة) تُعاد 4 مرات.
    send_fn(model) -> (kind, data): kind = ok | retry | bad_model | fatal
    """
    queue_ = [first_model]
    tried, errs, listed = [], {}, False
    while queue_:
        mdl = queue_.pop(0)
        if not mdl or mdl in tried:
            continue
        tried.append(mdl)
        for attempt in range(4):
            cancel.check()
            kind, data = send_fn(mdl)
            if kind == "ok":
                note = f"(تم استخدام الموديل البديل: {mdl})\n\n" if mdl != first_model else ""
                return note + data
            if kind == "fatal":
                raise RuntimeError(data)
            errs[mdl] = data
            if kind == "retry" and attempt < 3:
                wait = 5 * (attempt + 1)
                info_ar(f"⚠ {label} / {mdl} مشغول — محاولة {attempt + 1}/4، انتظار {wait}ث ({data[:80]})")
                cancel.sleep(wait)
                continue
            break
        if not listed:
            listed = True
            try:
                avail = list_fn()
            except Cancelled:
                raise
            except Exception as e:
                avail = []
                info_ar(f"ℹ️ تعذر جلب قائمة موديلات {label}: {e}")
            extra = [m for m in preferred if m in avail] if avail else list(preferred)
            extra += [m for m in avail if m not in extra]
            queue_.extend([m for m in extra if m not in tried][:5])
        if queue_:
            info_ar(f"↪ الانتقال إلى موديل آخر بعد فشل {mdl}")
    lines = "\n".join(f"- {m}: {e}" for m, e in errs.items())
    raise RuntimeError(f"فشل الاتصال بـ {label}:\n{lines}")


# ---------- Gemini ----------
def _gemini_sort_key(n):
    m = re.search(r'gemini-(\d+(?:\.\d+)?)', n)
    ver = float(m.group(1)) if m else 0.0
    pen = 1 if re.search(r'preview|exp|lite|thinking|\d{2,3}$', n) else 0
    tier = 0 if 'flash' in n else (1 if 'pro' in n else 2)
    return (pen, tier, -ver, n)


def list_gemini_models(api_key, cancel=None):
    """يجلب الموديلات المتاحة فعلاً لمفتاحك والتي تدعم generateContent."""
    cancel = cancel or CancelToken()
    names, token = [], None
    for _ in range(5):
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        r = http_call(cancel, "GET", f"{GEMINI_BASE}/models", headers={"x-goog-api-key": api_key},
                      params=params, timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {_api_error_text(r)}")
        js = r.json()
        for m in js.get("models", []):
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            n = (m.get("name") or "").replace("models/", "")
            if n.startswith("gemini") and not GEMINI_EXCLUDE.search(n):
                names.append(n)
        token = js.get("nextPageToken")
        if not token:
            break
    return sorted(set(names), key=_gemini_sort_key)


def call_gemini(api_key, model, file_path, instruction="اقرأ الملف", cancel=None, timeout=240):
    cancel = cancel or CancelToken()
    file_text = Path(file_path).read_text(encoding="utf-8")
    # بدون generationConfig عمداً: كل موديل يستخدم إعداداته الافتراضية فلا يحدث خطأ 400 بين الإصدارات.
    body = {"contents": [{"role": "user", "parts": [
        {"text": f"محتوى الملف المرفق ({Path(file_path).name}):\n\n{file_text}"},
        {"text": instruction}]}]}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    def send(mdl):
        url = f"{GEMINI_BASE}/models/{mdl}:generateContent"
        try:
            r = http_call(cancel, "POST", url, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            return "retry", f"خطأ شبكة: {e}"
        if r.status_code == 200:
            try:
                js = r.json()
            except ValueError:
                return "retry", "ردّ غير صالح (ليس JSON)"
            cands = js.get("candidates") or []
            if not cands:
                return "bad_model", f"لم يرجع نتيجة: {js.get('promptFeedback') or js}"
            parts = (cands[0].get("content") or {}).get("parts") or []
            text = "\n".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))
            if not text.strip():
                return "bad_model", f"ردّ فارغ (finishReason={cands[0].get('finishReason')})"
            return "ok", text
        msg = _api_error_text(r)
        low = msg.lower()
        if r.status_code in (400, 401, 403) and ("api key" in low or "api_key" in low or "location is not supported" in low):
            return "fatal", f"Gemini رفض الطلب (HTTP {r.status_code}): {msg}"
        if r.status_code in (429, 500, 502, 503, 504):
            return "retry", f"HTTP {r.status_code}: {msg}"
        return "bad_model", f"HTTP {r.status_code}: {msg}"

    return _run_models(model, send, lambda: list_gemini_models(api_key, cancel), GEMINI_PREFERRED, cancel, "Gemini")


# ---------- Claude API ----------
def list_claude_models(api_key, cancel=None):
    cancel = cancel or CancelToken()
    headers = {"x-api-key": api_key, "anthropic-version": CLAUDE_API_VERSION}
    r = http_call(cancel, "GET", f"{CLAUDE_BASE}/models", headers=headers, params={"limit": 100}, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {_api_error_text(r)}")
    return [m.get("id") for m in r.json().get("data", []) if m.get("id")]


def call_claude_api(api_key, model, file_path, instruction="اقرأ الملف", cancel=None, timeout=300):
    cancel = cancel or CancelToken()
    file_text = Path(file_path).read_text(encoding="utf-8")
    headers = {"x-api-key": api_key, "anthropic-version": CLAUDE_API_VERSION, "content-type": "application/json"}
    content = [{"type": "text", "text": f"محتوى الملف المرفق ({Path(file_path).name}):\n\n{file_text}"},
               {"type": "text", "text": instruction}]

    def send(mdl):
        body = {"model": mdl, "max_tokens": 8192, "messages": [{"role": "user", "content": content}]}
        try:
            r = http_call(cancel, "POST", f"{CLAUDE_BASE}/messages", headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            return "retry", f"خطأ شبكة: {e}"
        if r.status_code == 200:
            try:
                js = r.json()
            except ValueError:
                return "retry", "ردّ غير صالح (ليس JSON)"
            text = "\n".join(b.get("text", "") for b in js.get("content", []) if b.get("type") == "text")
            if not text.strip():
                return "bad_model", f"ردّ فارغ (stop_reason={js.get('stop_reason')})"
            return "ok", text
        msg = _api_error_text(r)
        if r.status_code in (401, 403) or "credit balance" in msg.lower():
            return "fatal", f"Claude API رفض الطلب (HTTP {r.status_code}): {msg}"
        if r.status_code in (429, 500, 502, 503, 504, 529):
            return "retry", f"HTTP {r.status_code}: {msg}"
        return "bad_model", f"HTTP {r.status_code}: {msg}"

    return _run_models(model, send, lambda: list_claude_models(api_key, cancel), CLAUDE_PREFERRED, cancel, "Claude API")


# ---------- Claude Code (مباشر بدون API) ----------
def find_claude_cli():
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    home = Path.home()
    for c in (home / ".local" / "bin" / "claude.exe", home / ".local" / "bin" / "claude",
              home / "AppData" / "Roaming" / "npm" / "claude.cmd", home / ".claude" / "local" / "claude"):
        try:
            if c.exists():
                return str(c)
        except OSError:
            pass
    return None


def call_claude_cli(file_path, cancel=None, timeout=900):
    """
    يشغّل Claude Code المثبّت على جهازك مباشرة (claude -p) ويمرر له الملف عبر stdin.
    لا يحتاج API: يستخدم حساب Claude المسجَّل في Claude Code (claude ثم /login).
    """
    cancel = cancel or CancelToken()
    exe = find_claude_cli()
    if not exe:
        raise RuntimeError("Claude Code غير مثبّت على هذا الجهاز.\nالتثبيت: npm install -g @anthropic-ai/claude-code\n"
                           "ثم شغّل الأمر claude في الطرفية مرة واحدة وسجّل الدخول.")
    data = Path(file_path).read_bytes()
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)      # ليستخدم تسجيل الدخول (الاشتراك) وليس مفتاح API
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    REQUESTS_DIR.mkdir(exist_ok=True)
    info_ar(f"⏳ تشغيل Claude Code مباشرة: {exe}")
    cancel.check()
    proc = subprocess.Popen([exe, "-p", CLI_PROMPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=str(REQUESTS_DIR), env=env, creationflags=flags,
                            start_new_session=(os.name != "nt"))
    cancel.proc = proc
    box = {}

    def run():
        try:
            box["res"] = proc.communicate(input=data)
        except Exception as e:
            box["exc"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    started = time.time()
    try:
        while th.is_alive():
            th.join(0.2)
            if cancel.is_set():
                _kill_process_tree(proc)
                raise Cancelled()
            if time.time() - started > timeout:
                _kill_process_tree(proc)
                raise RuntimeError(f"انتهت مهلة Claude Code ({timeout}ث).")
    finally:
        cancel.proc = None
    cancel.check()
    if "exc" in box:
        raise box["exc"]
    out, err = box["res"]
    out_t = (out or b"").decode("utf-8", errors="replace").strip()
    err_t = (err or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        msg = (err_t or out_t or "بدون رسالة")[:600]
        hint = ""
        if re.search(r'log ?in|auth|credential|sign ?in', msg, re.I):
            hint = "\nشغّل claude في الطرفية وسجّل الدخول (/login) ثم أعد المحاولة."
        raise RuntimeError(f"Claude Code أعاد خطأ (رمز {proc.returncode}):\n{msg}{hint}")
    if not out_t:
        raise RuntimeError("ردّ Claude Code فارغ." + (f"\n{err_t[:400]}" if err_t else ""))
    return out_t


def ask_ai(cfg, path, cancel):
    prov = cfg["provider"]
    if prov == PROV_CLAUDE_API:
        return call_claude_api(cfg["claude_key"], cfg["claude_model"], path, "اقرأ الملف", cancel)
    if prov == PROV_CLAUDE_CLI:
        return call_claude_cli(path, cancel)
    return call_gemini(cfg["gem_key"], cfg["gem_model"], path, "اقرأ الملف", cancel)


def provider_label(cfg):
    prov = cfg["provider"]
    if prov == PROV_CLAUDE_API:
        return f"Claude API ({cfg['claude_model']})"
    if prov == PROV_CLAUDE_CLI:
        return "Claude Code (مباشر)"
    return f"Gemini ({cfg['gem_model']})"


def clean_for_telegram(t):
    t = re.sub(r'\*\*', '', t)
    t = re.sub(r'^#{1,6}\s*', '', t, flags=re.M)
    t = re.sub(r'^\s*[\*\-]\s+', '• ', t, flags=re.M)
    return t.replace('`', '')

def split_text(text, limit=3800):
    chunks, cur = [], ""
    for line in text.splitlines(True):
        if len(cur) + len(line) > limit and cur:
            chunks.append(cur); cur = ""
        while len(line) > limit:
            chunks.append(line[:limit]); line = line[limit:]
        cur += line
    if cur.strip():
        chunks.append(cur)
    return chunks

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_text(text)
    for ch in chunks:
        r = requests.post(url, data={'chat_id': chat_id, 'text': ch, 'disable_web_page_preview': True}, timeout=20)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        time.sleep(0.5)
    return True, f"{len(chunks)} رسالة"

def send_telegram_file(token, chat_id, path, caption=""):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(path, "rb") as f:
        r = requests.post(url, data={'chat_id': chat_id, 'caption': caption[:1000]},
                          files={'document': (Path(path).name, f, 'text/plain')}, timeout=60)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    return True, Path(path).name

def send_to_external(url, text):
    """مستقبل خارجي (Webhook عام) — معلّق مؤقتاً عبر EXTERNAL_RECEIVER_ENABLED."""
    if not EXTERNAL_RECEIVER_ENABLED:
        return False, "المستقبل الخارجي معلّق مؤقتاً"
    r = requests.post(url, json={"symbol": SYMBOL, "text": text, "time": datetime.now().isoformat()}, timeout=20)
    return r.status_code < 300, f"HTTP {r.status_code}"

# ==========================================================
# جسر الهاتف (Phone Bridge): ربط اللوحة مع تطبيق الأندرويد
#   - محلي: خادم HTTP + اكتشاف تلقائي عبر UDP (نفس شبكة الواي فاي)
#   - Firebase: Realtime Database عبر REST (لا يحتاج أي مكتبة إضافية غير requests)
#   التطبيق يختار تلقائياً المتاح: محلي أولاً ثم Firebase.
# ==========================================================
import zlib
import socket
import hmac
import secrets
import platform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

BRIDGE_HTTP_PORT = 8765
BRIDGE_UDP_PORT = 8766
BRIDGE_QUIET_SEC = 25            # أثناء نشاط الهاتف لا تظهر نوافذ التنبيه على الكمبيوتر (تظهر في شريط الحالة)
BUSY_ACTIONS = ("connect", "fetch", "fetch_ai", "ai", "make_file", "tg_file")
LAST_REMOTE = [0.0]              # آخر وقت وصل فيه طلب من الهاتف
LAST_DIALOG = [""]               # آخر رسالة تنبيه تم كتمها (لتُرسل للهاتف كخطأ)


def new_pair_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def norm_code(c):
    return re.sub(r'[^A-Za-z0-9]', '', str(c or '')).upper()


def _ver(text):
    """رقم نسخة للمحتوى (0 = فارغ)."""
    if not text:
        return 0
    return (zlib.crc32(text.encode("utf-8")) & 0x7FFFFFFF) or 1


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))      # لا يرسل أي بيانات، فقط يحدد واجهة الشبكة
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _patch_dialogs():
    """أثناء نشاط الهاتف: لا نوافذ منبثقة على الكمبيوتر، بل تُكتم وتُرسل للهاتف/شريط الحالة."""
    for n in ("showinfo", "showwarning", "showerror"):
        real = getattr(messagebox, n)

        def mk(real=real):
            def f(title=None, message=None, **kw):
                if time.time() - LAST_REMOTE[0] < BRIDGE_QUIET_SEC:
                    LAST_DIALOG[0] = str(message)
                    return None
                return real(title, message, **kw)
            return f
        setattr(messagebox, n, mk())


_patch_dialogs()


def _make_handler(br):
    class H(BaseHTTPRequestHandler):
        server_version = "SMCBridge/1.0"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b)

        def _authed(self):
            t = norm_code(self.headers.get("X-Token", ""))
            return bool(t) and hmac.compare_digest(t.encode(), br.code_norm.encode())

        def do_GET(self):
            try:
                path, _, qs = self.path.partition("?")
                if path == "/ping":
                    return self._send(200, {"smc": 1, "name": br.name})
                if not self._authed():
                    return self._send(401, {"ok": False, "error": "رمز الربط غير صحيح"})
                LAST_REMOTE[0] = time.time()
                if path == "/state":
                    return self._send(200, br.snap)
                if path == "/content":
                    k = parse_qs(qs).get("k", [""])[0]
                    c = br.contents.get(k)
                    return self._send(200 if c else 404, c or {"ok": False, "error": "لا يوجد محتوى"})
                self._send(404, {"ok": False, "error": "مسار غير معروف"})
            except Exception as e:
                logger.error("bridge GET: %s", e)

        def do_POST(self):
            try:
                path = self.path.split("?")[0]
                if not self._authed():
                    return self._send(401, {"ok": False, "error": "رمز الربط غير صحيح"})
                LAST_REMOTE[0] = time.time()
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(n).decode("utf-8") if n else ""
                body = json.loads(raw) if raw.strip() else {}
                if path == "/act":
                    return self._send(200, br.handle(body.get("action"), body.get("params") or {}))
                self._send(404, {"ok": False, "error": "مسار غير معروف"})
            except Exception as e:
                try:
                    self._send(500, {"ok": False, "error": str(e)})
                except Exception:
                    pass
    return H


class Bridge:
    def __init__(self, app):
        self.app = app
        self.name = platform.node() or "PC"
        self.stop_ev = threading.Event()
        self.snap = {}
        self.contents = {}
        self.code_norm = ""
        self.fb_on = False
        self.fb_url = ""
        self.fb_secret = ""
        self.fb_status = "معطّل"
        self.http_port = 0
        self.httpd = None
        self.ip = "?"
        self._last_tick = 0.0
        self._fkey = None
        self._ftext = ""
        self._shown_dialog = ""
        self.started = False

    # ---------- تشغيل / إيقاف ----------
    def start(self):
        if self.started:
            return
        self.started = True
        self.ip = local_ip()
        self.tick(force=True)
        try:
            self.app.save_settings()          # لتثبيت رمز الربط الجديد
        except Exception:
            pass
        for port in range(BRIDGE_HTTP_PORT, BRIDGE_HTTP_PORT + 10):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(self))
                self.http_port = port
                break
            except OSError:
                continue
        if self.httpd is not None:
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
            info_ar(f"📱 الخادم المحلي للهاتف يعمل: http://{self.ip}:{self.http_port}")
        else:
            error_ar("⚠ تعذر تشغيل الخادم المحلي للهاتف (المنافذ مشغولة).")
        threading.Thread(target=self._udp_loop, daemon=True).start()
        threading.Thread(target=self._fb_loop, daemon=True).start()

    def stop(self):
        self.stop_ev.set()
        try:
            if self.httpd is not None:
                threading.Thread(target=self.httpd.shutdown, daemon=True).start()
        except Exception:
            pass

    def status_text(self):
        loc = f"محلي: {self.ip}:{self.http_port}" if self.http_port else "محلي: متوقف"
        return f"{loc}  |  Firebase: {self.fb_status}"

    # ---------- اكتشاف تلقائي (UDP) ----------
    def _udp_loop(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", BRIDGE_UDP_PORT))
            s.settimeout(1.0)
        except OSError as e:
            error_ar(f"⚠ تعذر تشغيل الاكتشاف التلقائي (UDP {BRIDGE_UDP_PORT}): {e}")
            return
        while not self.stop_ev.is_set():
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip() == b"SMC_DISCOVER":
                msg = json.dumps({"smc": 1, "port": self.http_port, "name": self.name}).encode("utf-8")
                try:
                    s.sendto(msg, addr)
                except OSError:
                    pass
        try:
            s.close()
        except Exception:
            pass

    # ---------- لقطة الحالة (تُبنى في خيط الواجهة فقط) ----------
    @staticmethod
    def _as_list(app, v):
        try:
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v]
            return [str(x) for x in app.tk.splitlist(v)]
        except Exception:
            return []

    def _c(self, name, text):
        return {"name": name, "text": text or "", "ver": _ver(text)}

    def _file_info(self):
        p = self.app.last_file
        if not p:
            return "", ""
        try:
            st = os.stat(p)
            key = (str(p), st.st_mtime_ns, st.st_size)
            if key != self._fkey:
                self._fkey = key
                self._ftext = Path(p).read_text(encoding="utf-8")
            return Path(p).name, self._ftext
        except Exception:
            return "", ""

    def tick(self, force=False):
        now = time.time()
        if not force and now - self._last_tick < 0.6:
            return
        self._last_tick = now
        a = self.app
        try:
            cfg = a.cfg()
            if not norm_code(cfg.get("br_code")):
                a.v["br_code"].set(new_pair_code())
                cfg = a.cfg()
            self.code_norm = norm_code(cfg["br_code"])
            self.fb_on = bool(a.br_fb_on.get())
            self.fb_url = cfg.get("br_fb_url", "")
            self.fb_secret = cfg.get("br_fb_secret", "")

            fname, ftext = self._file_info()
            lists = {
                "symbols": (list(a.sym_vis or a.sym_all) or [cfg["symbol"]])[:400],
                "providers": PROVIDERS,
                "gem_models": self._as_list(a, a.cb_gem.cget("values")),
                "claude_models": self._as_list(a, a.cb_claude.cget("values")),
                "tg_modes": ["يدوي", "تلقائي"],
                "presets": PRESET_PROMPTS,
            }
            contents = {
                "data": self._c("SMC_data.txt", a.data_text),
                "file": self._c(fname or "SMC_request.txt", ftext),
                "answer": self._c("SMC_answer.txt", a.last_answer),
                "prompt": self._c("prompt.txt", a.prompt_text.get("1.0", "end").rstrip("\n")),
                "lists": self._c("lists.json", json.dumps(lists, ensure_ascii=False)),
            }
            try:
                log_tail = a.log_box.get("end-41l", "end-1c")
            except Exception:
                log_tail = ""
            snap = {
                "ok": 1, "name": self.name,
                "mt5": bool(a.mt5_ok), "conn": a.lbl_conn.cget("text"),
                "busy": bool(a.busy), "ai": bool(a.ai_running),
                "status": a.lbl_status.cget("text"), "price": a.lbl_price.cget("text"),
                "symbol": cfg["symbol"],
                "tfs": {n: bool(v.get()) for n, v in a.tf_vars.items()},
                "chain": bool(a.chain.get()),
                "provider": cfg["provider"], "gem_model": cfg["gem_model"],
                "claude_model": cfg["claude_model"], "tg_mode": cfg["tg_mode"],
                "label": a.last_label or "",
                "vers": {k: c["ver"] for k, c in contents.items()},
                "log": log_tail.strip()[-3500:],
            }
            self.contents = contents
            self.snap = snap
            # رسالة تنبيه كُتمت بسبب نشاط الهاتف → تظهر في شريط الحالة
            d = LAST_DIALOG[0]
            if d and d != self._shown_dialog:
                self._shown_dialog = d
                a.lbl_status.config(text="ℹ️ " + d.splitlines()[0][:160])
            a.lbl_bridge.config(text=self.status_text())
        except Exception as e:
            logger.error("bridge tick: %s", e)

    # ---------- تنفيذ أوامر الهاتف ----------
    def handle(self, action, params):
        if action == "hb":
            return {"ok": True}
        LAST_REMOTE[0] = time.time()
        box = {}
        ev = threading.Event()

        def job():
            try:
                box["r"] = self._do(action, params if isinstance(params, dict) else {})
            except Exception as e:
                logger.exception("bridge action %s", action)
                box["r"] = {"ok": False, "error": f"خطأ على الكمبيوتر: {e}"}
            finally:
                ev.set()
        info_ar(f"📱 أمر من الهاتف: {action}")
        self.app.ui(job)
        if not ev.wait(20):
            return {"ok": False, "error": "انتهت مهلة التنفيذ على الكمبيوتر (هل اللوحة مفتوحة؟)"}
        return box.get("r") or {"ok": False, "error": "بدون ردّ"}

    def _apply(self, p):
        a = self.app
        sym = str(p.get("symbol") or "").strip()
        if sym and sym != a.v["symbol"].get().strip():
            a.v["symbol"].set(sym)
            a._apply_symbol_change()
        tfs = p.get("tfs")
        if isinstance(tfs, dict):
            for n, val in tfs.items():
                if n in a.tf_vars:
                    a.tf_vars[n].set(bool(val))
        if "chain" in p:
            a.chain.set(bool(p["chain"]))
        prov = p.get("provider")
        if prov in PROVIDERS and prov != a.v["provider"].get():
            a.v["provider"].set(prov)
            a._on_provider_change()
        for k in ("gem_model", "claude_model"):
            if p.get(k):
                a.v[k].set(str(p[k]))
        if p.get("tg_mode") in ("يدوي", "تلقائي"):
            a.v["tg_mode"].set(p["tg_mode"])

    def _do(self, action, p):
        a = self.app
        LAST_DIALOG[0] = ""
        if action in BUSY_ACTIONS and a.busy:
            return {"ok": False, "error": "الكمبيوتر مشغول بعملية أخرى — انتظر أو اضغط إيقاف"}
        if action == "connect":
            a.connect_async()
        elif action in ("fetch", "fetch_ai"):
            self._apply(p)
            a.start_fetch(action == "fetch_ai")
        elif action == "ai":
            self._apply(p)
            a.start_ai()
        elif action == "make_file":
            pth = a._prepare_file()
            if pth is None:
                return {"ok": False, "error": LAST_DIALOG[0] or "تعذر إنشاء الملف"}
            self.tick(force=True)
            text = Path(pth).read_text(encoding="utf-8")
            return {"ok": True, "name": Path(pth).name, "file_ver": _ver(text)}
        elif action == "tg_answer":
            a.send_telegram_async()
        elif action == "tg_file":
            a.send_file_telegram_async()
        elif action == "stop":
            a.stop_ai()
        elif action == "set":
            self._apply(p)
        elif action == "set_prompt":
            a._set_box(a.prompt_text, str(p.get("text", "")))
            a.prompt_text.tag_add("rtl", "1.0", "end")
        elif action == "reset_prompt":
            a.reset_prompts()
        elif action == "models":
            a.refresh_models_async()
        elif action == "save":
            a.save_settings()
        else:
            return {"ok": False, "error": f"أمر غير معروف: {action}"}
        msg = LAST_DIALOG[0]
        if msg and action != "set":
            return {"ok": False, "error": msg}
        self.tick(force=True)
        return {"ok": True}

    # ---------- Firebase (Realtime Database عبر REST) ----------
    def _fb(self, method, room, path, data=None):
        url = f"{self.fb_url.rstrip('/')}/rooms/{room}/{path}.json"
        params = {"auth": self.fb_secret} if self.fb_secret else None
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        return requests.request(method, url, params=params, data=body, timeout=10,
                                headers={"Content-Type": "application/json; charset=utf-8"})

    @staticmethod
    def _fb_check(r):
        if r.status_code in (401, 403):
            raise RuntimeError("Firebase رفض الوصول — راجع Rules أو السر")
        if r.status_code != 200:
            raise RuntimeError(f"Firebase HTTP {r.status_code}")

    def _fb_loop(self):
        last_cmd = None
        last_state_json = ""
        last_state_at = 0.0
        pushed = {}
        last_err = ""
        while not self.stop_ev.wait(1.2):
            if not (self.fb_on and self.fb_url.strip() and self.code_norm):
                self.fb_status = "معطّل"
                last_cmd = None
                pushed.clear()
                last_state_json = ""
                continue
            room = self.code_norm.lower()
            try:
                # 1) أوامر الهاتف
                r = self._fb("GET", room, "cmd")
                self._fb_check(r)
                cmd = r.json() if r.text.strip() not in ("", "null") else None
                if last_cmd is None:
                    last_cmd = cmd.get("id", "") if isinstance(cmd, dict) else ""
                elif isinstance(cmd, dict) and cmd.get("id") and cmd.get("id") != last_cmd:
                    last_cmd = cmd["id"]
                    act = cmd.get("action")
                    LAST_REMOTE[0] = time.time()
                    if act == "hb":
                        pass
                    else:
                        res = self.handle(act, cmd.get("params") or {})
                        self._fb("PUT", room, "resp", {"id": last_cmd, "res": res})
                # 2) الحالة (عند التغيّر أو كل 10 ثوانٍ كنبض حياة)
                snap = dict(self.snap)
                js = json.dumps(snap, ensure_ascii=False, sort_keys=True)
                now = time.time()
                if snap and (js != last_state_json or now - last_state_at > 10):
                    snap["ts"] = int(now)
                    self._fb_check(self._fb("PUT", room, "state", snap))
                    last_state_json, last_state_at = js, now
                # 3) المحتويات عند تغيّر نسختها
                for k, c in list(self.contents.items()):
                    if c["ver"] and pushed.get(k) != c["ver"]:
                        self._fb_check(self._fb("PUT", room, f"content/{k}", c))
                        pushed[k] = c["ver"]
                self.fb_status = "متصل ✅"
                last_err = ""
            except Exception as e:
                self.fb_status = f"خطأ ❌ {str(e)[:60]}"
                if str(e) != last_err:
                    last_err = str(e)
                    error_ar(f"⚠ Firebase: {e}")


# ==========================================================
# Control Panel (tkinter)
# ==========================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("لوحة تحكم SMC + Gemini / Claude")
        self.geometry("1180x820")
        self.minsize(980, 660)
        self.q = queue.Queue()
        self.busy = False
        self.mt5_ok = False
        self.mt5_lock = threading.Lock()
        self.data_text = ""
        self.last_answer = ""
        self.last_file = None
        self.last_label = ""
        self.cancel_token = None
        self.run_id = 0
        self.ai_running = False
        self.prompt_symbol = ""
        self.sym_all, self.sym_vis = [], []
        self.show_all_syms = tk.BooleanVar(value=False)
        self.v = {k: tk.StringVar() for k in
                  ["login", "password", "server", "symbol", "gem_key", "gem_model", "claude_key", "claude_model",
                   "provider", "tg_token", "tg_chat", "tg_mode", "br_code", "br_fb_url", "br_fb_secret"]}
        self.chain = tk.BooleanVar(value=False)
        self.save_keys = tk.BooleanVar(value=False)
        self.br_fb_on = tk.BooleanVar(value=False)
        self.tf_vars = {n: tk.BooleanVar(value=(n != "D1")) for n in TF_MAP}
        self._build_ui()
        self._load_settings()
        self.bridge = Bridge(self)
        self.after(900, self.bridge.start)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self.after(1800, lambda: self.refresh_models_async(True))   # تحديث صامت لقوائم الموديلات إن وُجدت مفاتيح
        self.after(600, self.connect_async)   # اتصال تلقائي بالمنصة بعد ظهور النافذة

    # ---------- UI ----------
    def _entry(self, parent, label, key, row, col, show=None, w=16):
        ttk.Label(parent, text=label).grid(row=row, column=col * 2, sticky="e", padx=4, pady=3)
        e = ttk.Entry(parent, textvariable=self.v[key], show=show, width=w)
        e.grid(row=row, column=col * 2 + 1, sticky="w", padx=4, pady=3)
        return e

    def _text_tab(self, nb, title, font=("Consolas", 10), wrap="word"):
        fr = ttk.Frame(nb)
        nb.add(fr, text=title)
        t = tk.Text(fr, wrap=wrap, font=font, undo=True)
        sb = ttk.Scrollbar(fr, command=t.yview)
        t.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return fr, t

    def _build_ui(self):
        try:
            ttk.Style(self).theme_use("clam")
        except Exception:
            pass
        pad = dict(padx=4, pady=3)

        f1 = ttk.LabelFrame(self, text=" 1) منصة MT5 (اترك رقم الحساب فارغاً لاستخدام الحساب المسجّل في المنصة) ")
        f1.pack(fill="x", padx=8, pady=(8, 3))
        self._entry(f1, "رقم الحساب", "login", 0, 0, w=12)
        self._entry(f1, "كلمة السر", "password", 0, 1, show="*", w=14)
        self._entry(f1, "السيرفر", "server", 0, 2, w=22)
        ttk.Label(f1, text="الرمز").grid(row=0, column=6, sticky="e", padx=4, pady=3)
        self.cb_symbol = ttk.Combobox(f1, textvariable=self.v["symbol"], width=16, state="readonly", values=[])
        self.cb_symbol.grid(row=0, column=7, sticky="w", padx=4, pady=3)
        self.cb_symbol.bind("<<ComboboxSelected>>", self.on_symbol_selected)
        ttk.Checkbutton(f1, text="عرض كل رموز المنصة", variable=self.show_all_syms,
                        command=self._fill_symbols).grid(row=1, column=6, columnspan=3, sticky="w", padx=4)
        self.b_connect = ttk.Button(f1, text="🔌 اتصال / إعادة اتصال", command=self.connect_async)
        self.b_connect.grid(row=0, column=8, **pad)
        self.lbl_conn = ttk.Label(f1, text="● غير متصل", foreground="#c0392b")
        self.lbl_conn.grid(row=0, column=9, **pad)

        f2 = ttk.LabelFrame(self, text=" 2) مفاتيح المزوّدين (Gemini / Claude) و Telegram ")
        f2.pack(fill="x", padx=8, pady=3)
        self._entry(f2, "Gemini API Key", "gem_key", 0, 0, show="*", w=30)
        ttk.Label(f2, text="موديل Gemini").grid(row=0, column=2, sticky="e", **pad)
        self.cb_gem = ttk.Combobox(f2, textvariable=self.v["gem_model"], width=26, values=GEMINI_MODELS_FALLBACK)
        self.cb_gem.grid(row=0, column=3, sticky="w", **pad)
        ttk.Checkbutton(f2, text="حفظ المفاتيح في ملف الإعدادات", variable=self.save_keys).grid(row=0, column=4, columnspan=3, sticky="w", **pad)
        self.b_models = ttk.Button(f2, text="🔄 تحديث قوائم الموديلات", command=self.refresh_models_async)
        self.b_models.grid(row=0, column=7, **pad)
        self._entry(f2, "Claude API Key", "claude_key", 1, 0, show="*", w=30)
        ttk.Label(f2, text="موديل Claude").grid(row=1, column=2, sticky="e", **pad)
        self.cb_claude = ttk.Combobox(f2, textvariable=self.v["claude_model"], width=26, values=CLAUDE_MODELS_FALLBACK)
        self.cb_claude.grid(row=1, column=3, sticky="w", **pad)
        self._entry(f2, "Telegram Token", "tg_token", 2, 0, show="*", w=30)
        self._entry(f2, "Chat ID", "tg_chat", 2, 1, w=16)
        ttk.Label(f2, text="إرسال النتيجة لـ Telegram").grid(row=2, column=4, sticky="e", **pad)
        ttk.Combobox(f2, textvariable=self.v["tg_mode"], width=10, state="readonly",
                     values=["يدوي", "تلقائي"]).grid(row=2, column=5, sticky="w", **pad)
        ttk.Checkbutton(f2, text="🌐 إرسال إلى مستقبل خارجي (معلّق مؤقتاً)", state="disabled").grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Entry(f2, state="disabled", width=40).grid(row=3, column=2, columnspan=3, sticky="w", **pad)

        f3 = ttk.LabelFrame(self, text=" 3) الفريمات والتنفيذ ")
        f3.pack(fill="x", padx=8, pady=3)
        for i, n in enumerate(TF_MAP):
            ttk.Checkbutton(f3, text=n, variable=self.tf_vars[n]).grid(row=0, column=i, **pad)
        ttk.Checkbutton(f3, text="تحليل تلقائياً بعد الجلب", variable=self.chain).grid(row=0, column=8, padx=14)
        pr = ttk.Frame(f3)
        pr.grid(row=1, column=0, columnspan=12, sticky="w", pady=2)
        ttk.Label(pr, text="مزوّد التحليل:").pack(side="left", padx=4)
        self.cb_provider = ttk.Combobox(pr, textvariable=self.v["provider"], values=PROVIDERS, state="readonly", width=34)
        self.cb_provider.pack(side="left", padx=4)
        self.cb_provider.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change())
        self.lbl_cli = ttk.Label(pr, text="")
        self.lbl_cli.pack(side="left", padx=10)
        bf = ttk.Frame(f3)
        bf.grid(row=2, column=0, columnspan=12, sticky="w", pady=4)
        self.b_fetch = ttk.Button(bf, text="📥 جلب البيانات الحية", command=lambda: self.start_fetch(False))
        self.b_gem = ttk.Button(bf, text="🤖 إنشاء الملف وإرساله للمزوّد", command=self.start_ai)
        self.b_all = ttk.Button(bf, text="⚡ جلب + تحليل", command=lambda: self.start_fetch(True))
        self.b_tg = ttk.Button(bf, text="📨 إرسال النتيجة إلى Telegram", command=self.send_telegram_async)
        self.b_tgfile = ttk.Button(bf, text="📎 إنشاء ملف وإرساله إلى Telegram", command=self.send_file_telegram_async)
        self.b_share = ttk.Menubutton(bf, text="📤 مشاركة ▾")
        share_menu = tk.Menu(self.b_share, tearoff=0)
        share_menu.add_command(label="📡 إنشاء ملف ومشاركته عبر البلوتوث", command=self.share_bluetooth)
        share_menu.add_command(label="💾 إنشاء ملف وحفظه في الجهاز...", command=self.save_file_to_device)
        self.b_share["menu"] = share_menu
        self.b_stop = ttk.Button(bf, text="⏹ إيقاف", command=self.stop_ai, state="disabled")
        for b in (self.b_fetch, self.b_gem, self.b_all, self.b_tg, self.b_tgfile, self.b_share, self.b_stop):
            b.pack(side="left", padx=5)
        self.action_buttons = [self.b_connect, self.b_fetch, self.b_gem, self.b_all, self.b_tg, self.b_tgfile,
                               self.b_share, self.b_models]

        f4 = ttk.LabelFrame(self, text=" 4) الربط مع تطبيق الهاتف (SMC Phone) — محلي تلقائي أو Firebase ")
        f4.pack(fill="x", padx=8, pady=3)
        self._entry(f4, "رمز الربط", "br_code", 0, 0, w=18)
        ttk.Button(f4, text="📋 نسخ", command=self.br_copy).grid(row=0, column=2, **pad)
        ttk.Button(f4, text="🔁 رمز جديد", command=self.br_newcode).grid(row=0, column=3, **pad)
        self.lbl_bridge = ttk.Label(f4, text="...", foreground="#1f4e79")
        self.lbl_bridge.grid(row=0, column=4, columnspan=4, sticky="w", **pad)
        ttk.Checkbutton(f4, text="تفعيل Firebase", variable=self.br_fb_on).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        self._entry(f4, "Firebase URL", "br_fb_url", 1, 1, w=40)
        self._entry(f4, "Secret (اختياري)", "br_fb_secret", 1, 2, show="*", w=18)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=3)

        # تبويب الأوامر
        fr = ttk.Frame(self.nb)
        self.nb.add(fr, text="الأوامر الافتراضية")
        bar = ttk.Frame(fr)
        bar.pack(fill="x", pady=3)
        self.preset_var = tk.StringVar()
        ttk.Combobox(bar, textvariable=self.preset_var, values=PRESET_PROMPTS, width=60).pack(side="left", padx=4)
        ttk.Button(bar, text="➕ إضافة أمر", command=self.add_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="💾 حفظ كأوامر افتراضية", command=self.save_settings).pack(side="left", padx=2)
        ttk.Button(bar, text="↩ استعادة الأصلي", command=self.reset_prompts).pack(side="left", padx=2)
        pf = ttk.Frame(fr)
        pf.pack(fill="both", expand=True)
        self.prompt_text = tk.Text(pf, wrap="word", font=("Segoe UI", 11), undo=True)
        sb = ttk.Scrollbar(pf, command=self.prompt_text.yview)
        self.prompt_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.prompt_text.pack(side="left", fill="both", expand=True)
        self.prompt_text.tag_configure("rtl", justify="right")
        self.prompt_text.bind("<KeyRelease>", lambda e: self.prompt_text.tag_add("rtl", "1.0", "end"))

        _, self.data_box = self._text_tab(self.nb, "البيانات المجلوبة")
        _, self.file_box = self._text_tab(self.nb, "الملف المُرسل (txt)")
        _, self.res_text = self._text_tab(self.nb, "نتيجة التحليل", font=("Segoe UI", 11))
        _, self.log_box = self._text_tab(self.nb, "السجل", font=("Consolas", 9))
        w = self.res_text
        w.tag_configure("rtl", justify="right")
        w.tag_configure("h1", font=("Segoe UI", 15, "bold"), foreground="#1f4e79", spacing1=10, spacing3=4)
        w.tag_configure("h2", font=("Segoe UI", 12, "bold"), foreground="#2e75b6", spacing1=6, spacing3=2)
        w.tag_configure("bold", font=("Segoe UI", 11, "bold"))

        sbar = ttk.Frame(self)
        sbar.pack(fill="x", padx=8, pady=(2, 6))
        self.progress = ttk.Progressbar(sbar, mode="indeterminate", length=140)
        self.progress.pack(side="left")
        self.lbl_status = ttk.Label(sbar, text="جاهز")
        self.lbl_status.pack(side="left", padx=8)
        self.lbl_price = ttk.Label(sbar, text="", foreground="#1f4e79", font=("Segoe UI", 10, "bold"))
        self.lbl_price.pack(side="right", padx=8)

    # ---------- bridge helpers ----------
    def br_copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.v["br_code"].get().strip())
            self.lbl_status.config(text="📋 تم نسخ رمز الربط")
        except Exception:
            pass

    def br_newcode(self):
        self.v["br_code"].set(new_pair_code())
        self.save_settings()
        self.lbl_status.config(text="🔁 تم إنشاء رمز ربط جديد — أدخله في التطبيق")

    # ---------- helpers ----------
    def ui(self, fn):
        self.q.put(fn)

    def _poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        try:
            n = 0
            while n < 200:
                line = UI_LOG_Q.get_nowait()
                self.log_box.insert("end", f"{datetime.now():%H:%M:%S}  {line}\n")
                n += 1
            if n:
                self.log_box.see("end")
        except queue.Empty:
            pass
        try:
            self.bridge.tick()
        except Exception:
            pass
        self.after(100, self._poll)

    def cfg(self):
        c = {k: v.get().strip() for k, v in self.v.items()}
        c["symbol"] = c["symbol"] or "XAUUSD"
        c["gem_model"] = c["gem_model"] or GEMINI_DEFAULT_MODEL
        c["claude_model"] = c["claude_model"] or CLAUDE_DEFAULT_MODEL
        if c["provider"] not in PROVIDERS:
            c["provider"] = PROV_GEMINI
        return c

    def set_busy(self, busy, text=None, ai=False):
        self.busy = busy
        self.ai_running = bool(busy and ai)
        for b in self.action_buttons:
            b.config(state="disabled" if busy else "normal")
        self.b_stop.config(state="normal" if self.ai_running else "disabled")
        self.progress.start(12) if busy else self.progress.stop()
        if text is not None:
            self.lbl_status.config(text=text)

    def status(self, text):
        self.ui(lambda: self.lbl_status.config(text=text))

    def _fail(self, msg):
        self.set_busy(False, "❌ " + msg)
        messagebox.showerror("خطأ", str(msg)[:900])

    def _set_box(self, box, text):
        box.config(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)

    # ---------- prompts ----------
    def add_preset(self):
        p = self.preset_var.get().strip()
        if p:
            n = len(re.findall(r'^\d+\.', self.prompt_text.get("1.0", "end"), flags=re.M)) + 1
            self.prompt_text.insert("end", f"\n{n}. {p}")
            self.prompt_text.tag_add("rtl", "1.0", "end")

    def reset_prompts(self):
        sym = self.v["symbol"].get().strip() or "XAUUSD"
        self.prompt_symbol = sym
        self._set_box(self.prompt_text, default_prompts(sym))
        self.prompt_text.tag_add("rtl", "1.0", "end")

    # ---------- symbols (تُجلب من المنصة) ----------
    def _fill_symbols(self):
        names = self.sym_all if self.show_all_syms.get() else (self.sym_vis or self.sym_all)
        cur = self.v["symbol"].get().strip()
        names = list(names)
        if cur and cur not in names:
            names.insert(0, cur)
        self.cb_symbol["values"] = names

    def _set_symbol_lists(self, names_all, names_vis):
        self.sym_all, self.sym_vis = names_all, names_vis
        cur = self.v["symbol"].get().strip()
        if names_all and cur not in names_all:
            cand = [n for n in names_all if n.upper().startswith(cur.upper())] if cur else []
            new = cand[0] if cand else (names_vis[0] if names_vis else names_all[0])
            info_ar(f"ℹ️ الرمز '{cur}' غير موجود في المنصة — تم اختيار '{new}' تلقائياً.")
            self.v["symbol"].set(new)
         