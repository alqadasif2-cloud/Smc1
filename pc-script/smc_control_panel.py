# -*- coding: utf-8 -*-
"""
SMC Control Panel + Gemini / Claude  (ملف واحد - لا يحتاج أي ملفات خارجية)
---------------------------------------------------------------------------
التشغيل:  python smc_control_panel.py
المتطلبات: pip install MetaTrader5 pandas numpy requests   (tkinter مدمجة مع بايثون)

سير العمل:
 1) تفتح لوحة التحكم ثم تتصل بمنصة MT5 تلقائياً.
 2) زر "جلب البيانات الحية" يحلل الفريمات المحددة ويعرض النتائج في اللوحة.
 3) زر "إنشاء الملف وإرساله للمزوّد" ينشئ ملف .txt (الأوامر + البيانات) ويرسله إلى المزوّد المختار:
    Gemini أو Claude (عبر API) أو Claude Code مباشرة بدون API، ويمكنك إيقاف الطلب بزر ⏹ في أي لحظة.
 4) تظهر النتيجة مرتبة في اللوحة، مع إرسالها إلى Telegram (يدوي أو تلقائي). زر "مشاركة" لحفظ الملف أو إرساله بلوتوث.
 5) المستقبل الخارجي موجود في الكود لكنه معلّق (EXTERNAL_RECEIVER_ENABLED = False).
 6) الربط مع تطبيق الأندرويد (SMC Phone) واللوحة السحابية:
    - محلي (نفس الواي فاي - اكتشاف تلقائي عبر UDP 8766 + HTTP 8765)
    - Firebase Firestore (مفعّل افتراضياً ومربوط بقاعدة بيانات واحدة جاهزة بدون أي إعداد يدوي)
    يختار تطبيق الهاتف القناة المتاحة تلقائياً (المحلي أولاً إن كان على نفس الشبكة، وإلا Firebase).
"""
import os
import re
import math
import json
import time
import queue
import zlib
import hmac
import socket
import secrets
import platform
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

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
DELTA_WINDOW_MIN = 15

DEFAULT_DELTA_PCT_TRIGGER = 12.0
DEFAULT_TICK_RATE_MULT = 2.5
DEFAULT_VOLUME_SPIKE_MULT = 3.0
XAU_DELTA_PCT_TRIGGER = 20.0
XAU_TICK_RATE_MULT = 3.0
XAU_VOLUME_SPIKE_MULT = 4.0

EXTERNAL_RECEIVER_ENABLED = False

# --------------------------
# إعدادات Firebase الافتراضية (قاعدة البيانات المشتركة الجاهزة)
# --------------------------
DEFAULT_FB_PROJECT_ID = "gen-lang-client-0819396986"
DEFAULT_FB_DATABASE_ID = "ai-studio-remotecontrolsyn-df2f1204-af22-4100-8861-97c8a605fa68"
DEFAULT_FB_API_KEY = "AIzaSyCtdkKUAcEa5pZjKxxk1t9HayIq_Pi-ehw"
DEFAULT_FB_URL = f"firestore://{DEFAULT_FB_PROJECT_ID}/{DEFAULT_FB_DATABASE_ID}"
DEFAULT_PAIR_CODE = "SMC-AUTO-BRIDGE"
DEFAULT_INTERNAL_AI_URL = "https://ais-pre-5as3ie4knpzuvhxk3weepk-38839718891.europe-west3.run.app/api/gemini/analyze"

# --------------------------
# مزوّدو التحليل
# --------------------------
PROV_GEMINI = "Gemini"
PROV_CLAUDE_API = "Claude (عبر API)"
PROV_CLAUDE_CLI = "Claude Code (مباشر بدون API)"
PROVIDERS = [PROV_GEMINI, PROV_CLAUDE_API, PROV_CLAUDE_CLI]

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
    u = str(symbol or "").upper()
    return f"الذهب ({symbol})" if ("XAU" in u or "GOLD" in u) else str(symbol)


def default_prompts(symbol):
    return DEFAULT_PROMPTS_TEMPLATE.replace("{asset}", asset_label(symbol))


def swap_symbol_in_text(text, old, new):
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
# Logging
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
    _out(text)
    logger.info(text)


def error_ar(text):
    _out(text)
    logger.error(text)


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
# Analysis core
# ==========================================================
def get_rates_tf(tf, count=1200, end_dt_utc=None):
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
        for c in ['open', 'high', 'low', 'close', 'tick_volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        info_ar(f"✅ تم جلب وتحضير بيانات الفريم {tf} بنجاح. عدد الشموع: {len(df)}")
        return df
    except Exception as e:
        exception_ar(f"❌ استثناء عند جلب البيانات للفريم {tf}.", e)
        return None


def add_indicators(df):
    try:
        info_ar("🔢 حساب المؤشرات الأساسية (SMA, EMA, ATR, body, ADX)...")
        for p in [10, 14, 50, 100, 200]:
            df[f'SMA_{p}'] = df['close'].rolling(p, min_periods=1).mean()
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['body'] = (df['close'] - df['open']).abs()
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = (df['high'] - df['close'].shift(1)).abs()
        df['tr3'] = (df['low'] - df['close'].shift(1)).abs()
        df['TR'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['ATR'] = df['TR'].rolling(ATR_PERIOD, min_periods=1).mean()

        df['up_move'] = df['high'].diff()
        df['down_move'] = -df['low'].diff()
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)

        alpha = 1.0 / float(ADX_PERIOD)
        df['TR_smooth'] = df['TR'].ewm(alpha=alpha, adjust=False).mean()
        df['plus_dm_smooth'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean()
        df['minus_dm_smooth'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()

        df['PLUS_DI_14'] = np.where(df['TR_smooth'] > 0, 100.0 * (df['plus_dm_smooth'] / df['TR_smooth']), 0.0)
        df['MINUS_DI_14'] = np.where(df['TR_smooth'] > 0, 100.0 * (df['minus_dm_smooth'] / df['TR_smooth']), 0.0)
        df['DX_14'] = np.where(
            (df['PLUS_DI_14'] + df['MINUS_DI_14']) > 0,
            100.0 * (np.abs(df['PLUS_DI_14'] - df['MINUS_DI_14']) / (df['PLUS_DI_14'] + df['MINUS_DI_14'])),
            0.0,
        )
        df['ADX_14'] = df['DX_14'].ewm(alpha=alpha, adjust=False).mean()
        info_ar("✅ انتهى حساب المؤشرات.")
        return df
    except Exception as e:
        exception_ar("❌ خطأ أثناء حساب المؤشرات.", e)
        raise


def pivothigh_series(df, length):
    highs = df['high'].values
    n = len(highs)
    ph = np.full(n, np.nan)
    for i in range(length, n - length):
        window = highs[i - length:i + length + 1]
        if highs[i] == np.max(window):
            ph[i] = highs[i]
    return pd.Series(ph, index=df.index)


def pivotlow_series(df, length):
    lows = df['low'].values
    n = len(lows)
    pl = np.full(n, np.nan)
    for i in range(length, n - length):
        window = lows[i - length:i + length + 1]
        if lows[i] == np.min(window):
            pl[i] = lows[i]
    return pd.Series(pl, index=df.index)


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
    last_low = float(pl.iloc[-1]) if len(pl) >= 1 else float(df['low'].rolling(200).min().iloc[-1])
    prev_high = float(ph.iloc[-2]) if len(ph) >= 2 else None
    prev_low = float(pl.iloc[-2]) if len(pl) >= 2 else None
    return last_high, last_low, prev_high, prev_low


def detect_structure(df):
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


def detect_order_block(df, lookback=600, body_factor=1.7, confirm_bars=3):
    d = df.reset_index(drop=True).copy()
    d['avg_body'] = d['body'].rolling(20, min_periods=5).mean().bfill()
    max_look = min(len(d) - confirm_bars - 2, lookback)
    for i in range(len(d) - confirm_bars - 2, len(d) - max_look - 1, -1):
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
            if is_bull and net > avg_b * 0.6:
                zl = float(d.at[i - 1, 'low'])
                zh = float(d.at[i - 1, 'high'])
            elif (not is_bull) and net < -avg_b * 0.6:
                zl = float(d.at[i - 1, 'low'])
                zh = float(d.at[i - 1, 'high'])
            else:
                continue
            post = d.loc[i + 1:, 'close']
            tested = post[(post >= zl) & (post <= zh)]
            status = "Tested" if not tested.empty else "Untested"
            zone_str = f"{'Bull' if is_bull else 'Bear'}_Zone[{round(zl, 4)}-{round(zh, 4)}]"
            info_ar(f"🔍 تم العثور على Order Block: {zone_str} (Status: {status})")
            return zone_str, i - 1, status
    info_ar("ℹ️ لم يتم العثور على Order Block حديث.")
    return "None", None, None


def volume_profile_poc_boxes(df, bins=VOL_BIN_COUNT, threshold_mult=HV_MULTIPLIER):
    prices = df['close'].values
    vols = df['tick_volume'].values.astype(float)
    if np.nansum(vols) == 0:
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
                lo = float(edges[group[0]])
                hi = float(edges[group[-1] + 1])
                boxes.append((round(lo, 4), round(hi, 4)))
                group = [k]
        lo = float(edges[group[0]])
        hi = float(edges[group[-1] + 1])
        boxes.append((round(lo, 4), round(hi, 4)))
    return round(poc, 4), boxes


def auto_fib_levels(df):
    ph = pivothigh_series(df, PIVOT_LENGTH).dropna()
    pl = pivotlow_series(df, PIVOT_LENGTH).dropna()
    if ph.empty or pl.empty:
        max_p = df['high'].rolling(FIB_DEPTH).max().iloc[-1]
        min_p = df['low'].rolling(FIB_DEPTH).min().iloc[-1]
    else:
        last_high = ph.iloc[-1]
        last_low = pl.iloc[-1]
        if last_high > last_low:
            max_p = last_high
            min_p = last_low
        else:
            max_p = df['high'].rolling(FIB_DEPTH).max().iloc[-1]
            min_p = df['low'].rolling(FIB_DEPTH).min().iloc[-1]
    diff = max_p - min_p
    if diff == 0:
        return {}
    return {
        "0.236": round(min_p + 0.236 * diff, 4),
        "0.382": round(min_p + 0.382 * diff, 4),
        "0.5": round(min_p + 0.5 * diff, 4),
        "0.618": round(min_p + 0.618 * diff, 4),
        "0.786": round(min_p + 0.786 * diff, 4),
        "1.0": round(max_p, 4),
        "1.272": round(min_p + 1.272 * diff, 4),
        "1.414": round(min_p + 1.414 * diff, 4),
        "1.618": round(min_p + 1.618 * diff, 4),
        "1.786": round(min_p + 1.786 * diff, 4),
        "2.0": round(min_p + 2.0 * diff, 4),
    }


def detect_liquidity_raid(df, lookback=30):
    try:
        h_target = float(df['high'].iloc[-lookback:-1].max())
        l_target = float(df['low'].iloc[-lookback:-1].min())
    except Exception:
        return "Stable", None, None
    c_h = float(df['high'].iloc[-1])
    c_c = float(df['close'].iloc[-1])
    c_l = float(df['low'].iloc[-1])
    if c_h > h_target and c_c < h_target:
        return "Raid High ⚡", h_target, l_target
    if c_l < l_target and c_c > l_target:
        return "Raid Low ⚡", h_target, l_target
    return "Stable", h_target, l_target


def compute_vwap_deviation_last_n(df, n_bars=VWAP_WINDOW_BARS):
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


def detect_volume_spike(df, lookback_bars=5, mult=DEFAULT_VOLUME_SPIKE_MULT):
    if len(df) < lookback_bars + 1:
        return False, None, None
    last_vol = float(df['tick_volume'].iloc[-1])
    avg_vol = float(df['tick_volume'].iloc[-(lookback_bars + 1):-1].mean())
    if avg_vol == 0:
        return False, last_vol, avg_vol
    return (last_vol >= (mult * avg_vol)), last_vol, avg_vol


def compute_signal_for_tf(symbol, df, ob_zone, ob_status, vwap_info, delta_info, tick_rates, is_volume_spike, thresholds):
    score = 0.0
    delta_pct = delta_info.get('delta_pct', 0.0)
    vwap_dev = vwap_info.get('deviation_pct') if vwap_info is not None else 0.0
    tick_rate_now = tick_rates.get('tick_rate_now', 0.0)
    avg_tick_rate = tick_rates.get('avg_tick_rate', 0.0)
    tick_rate_condition = avg_tick_rate > 0 and tick_rate_now >= (thresholds['tick_rate_mult'] * avg_tick_rate)
    vol_cond = bool(is_volume_spike)
    ob_cond = (ob_zone is not None and ob_zone != "None" and (ob_status == "Tested"))
    delta_cond = abs(delta_pct) >= thresholds['delta_pct']
    vwap_dir_cond = (delta_pct > 0 and vwap_dev is not None and vwap_dev > 0) or (
        delta_pct < 0 and vwap_dev is not None and vwap_dev < 0
    )

    weights = {'delta': 35, 'vwap_dir': 20, 'tick_rate': 15, 'volume_spike': 15, 'order_block': 15}
    if delta_cond:
        score += weights['delta']
    if vwap_dir_cond:
        score += weights['vwap_dir']
    if tick_rate_condition:
        score += weights['tick_rate']
    if vol_cond:
        score += weights['volume_spike']
    if ob_cond:
        score += weights['order_block']

    direction = None
    if delta_cond and vwap_dir_cond:
        direction = 'Long' if delta_pct > 0 else 'Short'
    else:
        satisfied = sum([delta_cond, vwap_dir_cond, tick_rate_condition, vol_cond, ob_cond])
        if satisfied >= 3:
            direction = 'Long' if delta_pct > 0 else 'Short'

    score = min(max(score, 0.0), 100.0)
    checks = {
        'delta_pct': delta_pct, 'vwap_dev': vwap_dev,
        'tick_rate_now': tick_rate_now, 'avg_tick_rate': avg_tick_rate,
        'tick_rate_condition': tick_rate_condition, 'volume_spike': vol_cond,
        'order_block_tested': ob_cond,
    }
    return direction, int(score), checks


def detect_false_breakout(df, level_price, direction, delta_info, tick_rate_info, vwap_info, thresholds,
                          lookahead_bars=3, retest_bars=5, wick_factor=1.2, atr_multiplier_noise=0.25):
    try:
        res = {'is_false': False, 'reason': None, 'score': 0, 'details': {}}
        if df is None or len(df) < 3:
            res['reason'] = 'insufficient_data'
            return res

        last_close = float(df['close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1]) if 'ATR' in df.columns and not pd.isna(df['ATR'].iloc[-1]) else None
        if atr is None:
            atr = float((df['high'] - df['low']).rolling(5, min_periods=1).mean().iloc[-1])

        movement = abs(last_close - level_price)
        if atr > 0 and movement < (atr * atr_multiplier_noise):
            res['is_false'] = True
            res['reason'] = 'noise_vs_ATR'
            return res

        looked = df.iloc[-(lookahead_bars + 1):].copy()
        reversed_inside = False
        for idx in range(1, len(looked)):
            c = float(looked['close'].iloc[idx])
            if (direction == 'Long' and c <= level_price) or (direction == 'Short' and c >= level_price):
                reversed_inside = True
                break
        if reversed_inside:
            res['is_false'] = True
            res['reason'] = 'quick_reversal'
            return res

        max_wick = 0.0
        for i in range(1, min(lookahead_bars + 1, len(looked))):
            o = float(looked['open'].iloc[i])
            h = float(looked['high'].iloc[i])
            l = float(looked['low'].iloc[i])
            c = float(looked['close'].iloc[i])
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
            return res

        ticks_now = tick_rate_info.get('tick_rate_now', 0.0)
        avg_tick = tick_rate_info.get('avg_tick_rate', 0.0)
        tick_cond = avg_tick > 0 and ticks_now >= thresholds.get('tick_rate_mult', 2.0) * avg_tick
        last_vol = float(df['tick_volume'].iloc[-1]) if 'tick_volume' in df.columns else 0.0
        avg_vol = float(df['tick_volume'].iloc[-6:-1].mean()) if len(df) >= 6 else last_vol
        vol_cond = avg_vol > 0 and last_vol >= thresholds.get('volume_mult', 3.0) * avg_vol
        delta_pct = delta_info.get('delta_pct', 0.0)
        delta_dir_cond = (delta_pct > 0 and direction == 'Long') or (delta_pct < 0 and direction == 'Short')
        confirm_count = sum([tick_cond, vol_cond, delta_dir_cond])
        if confirm_count < 2:
            res['is_false'] = True
            res['reason'] = 'lack_of_confirmation'
            return res

        if len(df) >= retest_bars + 1:
            recent = df.iloc[-retest_bars:].copy()
            for i in range(len(recent)):
                rc = float(recent['close'].iloc[i])
                rh = float(recent['high'].iloc[i])
                rl = float(recent['low'].iloc[i])
                if (direction == 'Long' and rl <= level_price and rc <= level_price) or (
                    direction == 'Short' and rh >= level_price and rc >= level_price
                ):
                    res['is_false'] = True
                    res['reason'] = 'failed_retest'
                    return res

        score = (30 if tick_cond else 0) + (30 if vol_cond else 0) + (30 if delta_dir_cond else 0)
        vwap_dev = vwap_info.get('deviation_pct') if vwap_info else 0.0
        if (direction == 'Long' and vwap_dev and vwap_dev > 0) or (direction == 'Short' and vwap_dev and vwap_dev < 0):
            score += 10
        res['score'] = min(100, int(score))
        res['reason'] = 'confirmed_by_checks'
        return res
    except Exception as e:
        return {'is_false': False, 'reason': 'error', 'score': 0, 'details': {'exception': str(e)}}


_TICK_CACHE = {"key": None, "ts": 0.0, "val": None}


def _recent_ticks(symbol, minutes=60, max_ticks=MAX_TICKS_FETCH):
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
    if arr is None or len(arr) < 2:
        return {'delta': 0.0, 'delta_abs': 0.0, 'delta_pct': 0.0, 'ticks': 0 if arr is None else len(arr)}
    mid = (arr['bid'].astype(float) + arr['ask'].astype(float)) / 2.0
    sign = np.sign(np.diff(mid))
    vol = arr['volume'][1:].astype(float)
    w = np.where(vol > 0, vol, 1.0)
    delta = float((sign * w).sum())
    total = float(w.sum())
    return {
        'delta': delta,
        'delta_abs': abs(delta),
        'delta_pct': (delta / total * 100.0) if total > 0 else 0.0,
        'ticks': int(len(arr)),
    }


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
        return {
            'tick_rate_now': len(recent) / float(DELTA_WINDOW_MIN),
            'avg_tick_rate': avg_rate,
            'ticks_now': len(recent),
            'ticks_hist': len(ticks),
            'delta_info': delta_info,
        }
    except Exception as e:
        exception_ar("❌ خطأ أثناء حساب tick rates/delta.", e)
        return {'tick_rate_now': 0.0, 'avg_tick_rate': 0.0, 'ticks_now': 0, 'ticks_hist': 0, 'delta_info': empty}


def detect_false_breakout_safe(df, level_price, direction, **kw):
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
        spike, last_vol, avg_vol = detect_volume_spike(df.iloc[:-1], lookback_bars=5, mult=th['volume_mult'])
        session_start = bool(tr['avg_tick_rate'] > 0 and tr['tick_rate_now'] >= th['tick_rate_mult'] * tr['avg_tick_rate'] and spike)
        direction, score, _ = compute_signal_for_tf(SYMBOL, df, ob_zone, ob_status, vwap, delta, tr, spike, th)

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
        candles = [
            f"  {t:%m-%d %H:%M} | O {o:.2f} H {h:.2f} L {l:.2f} C {c:.2f} | V {int(v)}"
            for t, o, h, l, c, v in df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].tail(8).itertuples(index=False)
        ]
        return {"TimeFrame": name, "fields": fields, "candles": candles}
    except Exception as e:
        exception_ar(f"❌ فشل تحليل الفريم {name}.", e)
        return None


def get_current_price(symbol):
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
        return {
            "bid": bid, "ask": ask, "mid": (bid + ask) / 2.0, "spread": ask - bid, "digits": digits,
            "tick_time": datetime.fromtimestamp(int(t.time), tz=timezone.utc),
            "captured": datetime.now(SAUDI_TZ),
        }
    except Exception as e:
        exception_ar("⚠ تعذر جلب السعر الحالي.", e)
        return None


def fmt_price(price, key="bid"):
    return f"{price[key]:.{price['digits']}f}"


def rows_to_text(rows, symbol, price=None, fetch_time=None):
    now = (fetch_time or datetime.now(SAUDI_TZ)).strftime('%d/%m/%Y %H:%M:%S')
    out = [f"الرمز: {symbol}", f"وقت الجلب (الرياض): {now}", "=" * 50]
    if price:
        out.append(f"💰 السعر الحالي الآن: {fmt_price(price)}  (Bid) — هذا هو السعر الحالي الحي لحظة جلب البيانات")
        out.append(f"   Bid: {fmt_price(price)} | Ask: {fmt_price(price, 'ask')} | Spread: {price['spread']:.{price['digits']}f}")
        out.append(f"   وقت التيك (وقت خادم المنصة): {price['tick_time']:%Y-%m-%d %H:%M:%S} | وقت الجلب (الرياض): {price['captured']:%H:%M:%S}")
    else:
        out.append("⚠ تعذّر جلب السعر الحالي (لا يوجد تيك من المنصة — قد يكون السوق مغلقاً).")
    out.append("=" * 50)
    out += [
        "ملاحظة: الشمعة الأخيرة في كل فريم قد تكون غير مكتملة، و'سعر آخر شمعة' هو إغلاق الشمعة الجارية وليس بالضرورة السعر الحالي.",
        f"ملاحظة: Delta وTickRate محسوبان من تيكات آخر {DELTA_WINDOW_MIN} دقيقة وهما متطابقان في كل الفريمات.",
        "",
    ]
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
# Gemini / Claude / Telegram
# --------------------------
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
CLAUDE_BASE = "https://api.anthropic.com/v1"
CLAUDE_API_VERSION = "2023-06-01"
GEMINI_EXCLUDE = re.compile(r'embed|tts|image|live|audio|aqa|robot|computer|veo|imagen|deep-research|learnlm', re.I)
CLI_PROMPT = ("Read the attached file content (provided via stdin) and follow the instructions inside it "
              "exactly. Write the whole answer in Arabic.")


class Cancelled(Exception):
    pass


def _kill_process_tree(p):
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
                info_ar(f"⚠ {label} / {mdl} مشغول — محاولة {attempt + 1}/4، انتظار {wait}ث")
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
    lines = "\n".join(f"- {m}: {e}" for m, e in errs.items())
    raise RuntimeError(f"فشل الاتصال بـ {label}:\n{lines}")


def _gemini_sort_key(n):
    m = re.search(r'gemini-(\d+(?:\.\d+)?)', n)
    ver = float(m.group(1)) if m else 0.0
    pen = 1 if re.search(r'preview|exp|lite|thinking|\d{2,3}$', n) else 0
    tier = 0 if 'flash' in n else (1 if 'pro' in n else 2)
    return (pen, tier, -ver, n)


def list_gemini_models(api_key, cancel=None):
    cancel = cancel or CancelToken()
    names, token = [], None
    for _ in range(5):
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        r = http_call(cancel, "GET", f"{GEMINI_BASE}/models", headers={"x-goog-api-key": api_key}, params=params, timeout=25)
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
    body = {"contents": [{"role": "user", "parts": [
        {"text": f"محتوى الملف المرفق ({Path(file_path).name}):\n\n{file_text}"},
        {"text": instruction},
    ]}]}
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
    cancel = cancel or CancelToken()
    exe = find_claude_cli()
    if not exe:
        raise RuntimeError("Claude Code غير مثبّت على هذا الجهاز.\nالتثبيت: npm install -g @anthropic-ai/claude-code\n"
                           "ثم شغّل الأمر claude في الطرفية مرة واحدة وسجّل الدخول.")
    data = Path(file_path).read_bytes()
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
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
        hint = "\nشغّل claude في الطرفية وسجّل الدخول (/login) ثم أعد المحاولة." if re.search(r'log ?in|auth|credential|sign ?in', msg, re.I) else ""
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
            chunks.append(cur)
            cur = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
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
    if not EXTERNAL_RECEIVER_ENABLED:
        return False, "المستقبل الخارجي معلّق مؤقتاً"
    r = requests.post(url, json={"symbol": SYMBOL, "text": text, "time": datetime.now().isoformat()}, timeout=20)
    return r.status_code < 300, f"HTTP {r.status_code}"


# ==========================================================
# جسر الهاتف (Phone Bridge): محلي + Firebase Firestore (افتراضي)
# ==========================================================
BRIDGE_HTTP_PORT = 8765
BRIDGE_UDP_PORT = 8766
BRIDGE_QUIET_SEC = 25
BUSY_ACTIONS = ("connect", "fetch", "fetch_ai", "ai", "make_file", "tg_file")
CHART_REMOTE_INTERVAL = 60.0
LAST_REMOTE = [0.0]
LAST_DIALOG = [""]


def new_pair_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def norm_code(c):
    return re.sub(r'[^A-Za-z0-9]', '', str(c or '')).upper()


def _ver(text):
    if not text:
        return 0
    return (zlib.crc32(text.encode("utf-8")) & 0x7FFFFFFF) or 1


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _patch_dialogs():
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


def _fs_encode_val(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _fs_encode_doc(d):
    return {"fields": {str(k): _fs_encode_val(v) for k, v in d.items() if v is not None}}


def _fs_decode_val(obj):
    if not isinstance(obj, dict):
        return None
    if "stringValue" in obj:
        return obj["stringValue"]
    if "booleanValue" in obj:
        return bool(obj["booleanValue"])
    if "integerValue" in obj:
        return int(obj["integerValue"])
    if "doubleValue" in obj:
        return float(obj["doubleValue"])
    if "mapValue" in obj:
        f = obj["mapValue"].get("fields") or {}
        return {k: _fs_decode_val(v) for k, v in f.items()}
    return None


def _fs_decode_doc(js):
    if not isinstance(js, dict) or "fields" not in js:
        return {}
    return {k: _fs_decode_val(v) for k, v in (js.get("fields") or {}).items()}


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
        self.name = (platform.node() or "PC")[:120]
        self.stop_ev = threading.Event()
        self.snap = {}
        self.contents = {}
        self.code_norm = ""
        self.fb_on = True
        self.fb_url = DEFAULT_FB_URL
        self.fb_secret = DEFAULT_FB_API_KEY
        self.fb_status = "جاري الاتصال..."
        self.http_port = 0
        self.httpd = None
        self.ip = "?"
        self._last_tick = 0.0
        self._fkey = None
        self._ftext = ""
        self._shown_dialog = ""
        self.started = False

    def start(self):
        if self.started:
            return
        self.started = True
        self.ip = local_ip()
        self.tick(force=True)
        try:
            self.app.save_settings()
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

    @staticmethod
    def _as_list(app, v):
        try:
            if isinstance(v, (list, tuple)):
                return [str(x) for x in v]
            return [str(x) for x in app.tk.splitlist(v)]
        except Exception:
            return []

    def _c(self, name, text):
        t = (text or "")[:700000]
        return {"name": name[:160], "text": t, "ver": _ver(t)}

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
                a.v["br_code"].set(DEFAULT_PAIR_CODE)
                cfg = a.cfg()
            self.code_norm = norm_code(cfg["br_code"])
            self.fb_on = bool(a.br_fb_on.get())
            self.fb_url = cfg.get("br_fb_url", "") or DEFAULT_FB_URL
            self.fb_secret = cfg.get("br_fb_secret", "") or DEFAULT_FB_API_KEY

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
                "chart": self._c("SMC_chart.json", a.chart_json),
            }
            try:
                log_tail = a.log_box.get("end-41l", "end-1c")
            except Exception:
                log_tail = ""
            snap = {
                "ok": 1, "name": self.name[:120],
                "mt5": bool(a.mt5_ok), "conn": str(a.lbl_conn.cget("text"))[:120],
                "busy": bool(a.busy), "ai": bool(a.ai_running),
                "status": str(a.lbl_status.cget("text"))[:400],
                "price": str(a.lbl_price.cget("text"))[:240],
                "symbol": str(cfg["symbol"])[:40],
                "tfs": {n: bool(v.get()) for n, v in a.tf_vars.items()},
                "chain": bool(a.chain.get()),
                "provider": str(cfg["provider"])[:80],
                "gem_model": str(cfg["gem_model"])[:100],
                "claude_model": str(cfg["claude_model"])[:100],
                "tg_mode": str(cfg["tg_mode"])[:30],
                "label": str(a.last_label or "")[:120],
                "chart_active": bool(a.chart_active),
                "chart_tf": str(a.chart_tf or "M15")[:12],
                "vers": {k: c["ver"] for k, c in contents.items()},
                "log": log_tail.strip()[-3500:],
            }
            self.contents = contents
            self.snap = snap
            d = LAST_DIALOG[0]
            if d and d != self._shown_dialog:
                self._shown_dialog = d
                a.lbl_status.config(text="ℹ️ " + d.splitlines()[0][:160])
            a.lbl_bridge.config(text=self.status_text())
        except Exception as e:
            logger.error("bridge tick: %s", e)

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
        elif action == "chart_start":
            tf = str(p.get("tf") or "").strip()
            a.start_live_chart(tf=(tf if tf in TF_MAP else None), switch_tab=True, force_remote=True)
        elif action == "chart_stop":
            a.stop_live_chart()
        elif action == "chart_tf":
            tf = str(p.get("tf") or "").strip()
            if tf in TF_MAP:
                a.set_chart_timeframe(tf, force_remote=True)
        elif action == "chart_refresh":
            tf = str(p.get("tf") or "").strip()
            if tf in TF_MAP:
                a.chart_tf = tf
            a.refresh_live_chart_once()
        elif action in ("internal_gemini", "make_file_internal_gemini"):
            if action == "make_file_internal_gemini":
                pth = a._prepare_file()
                if pth is None:
                    return {"ok": False, "error": LAST_DIALOG[0] or "اجلب البيانات الحية أولاً"}
                self.tick(force=True)
            a.start_internal_gemini(remote_relay=True)
        else:
            return {"ok": False, "error": f"أمر غير معروف: {action}"}
        msg = LAST_DIALOG[0]
        if msg and action != "set":
            return {"ok": False, "error": msg}
        self.tick(force=True)
        return {"ok": True}

    # ---------- Firebase (Firestore REST افتراضياً + دعم RTDB) ----------
    def _is_firestore(self):
        u = (self.fb_url or "").strip()
        return u.startswith("firestore://") or "firestore.googleapis.com" in u

    def _fs_base(self):
        u = (self.fb_url or "").strip()
        if u.startswith("firestore://"):
            rest = u[len("firestore://"):].strip("/")
            parts = rest.split("/", 1)
            proj = parts[0] or DEFAULT_FB_PROJECT_ID
            db = parts[1] if len(parts) > 1 and parts[1] else "(default)"
            return f"https://firestore.googleapis.com/v1/projects/{proj}/databases/{db}/documents"
        return u.rstrip("/")

    def _fs_req(self, method, doc_path, payload=None):
        url = f"{self._fs_base()}/{doc_path.lstrip('/')}"
        key = (self.fb_secret or "").strip() or DEFAULT_FB_API_KEY
        params = {"key": key} if key else None
        body = json.dumps(_fs_encode_doc(payload), ensure_ascii=False).encode("utf-8") if payload is not None else None
        return requests.request(method, url, params=params, data=body, timeout=12,
                                headers={"Content-Type": "application/json; charset=utf-8"})

    def _rtdb(self, method, room, path, data=None):
        url = f"{self.fb_url.rstrip('/')}/rooms/{room}/{path}.json"
        params = {"auth": self.fb_secret} if self.fb_secret else None
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        return requests.request(method, url, params=params, data=body, timeout=10,
                                headers={"Content-Type": "application/json; charset=utf-8"})

    @staticmethod
    def _fb_check(r, allow_404=False):
        if allow_404 and r.status_code == 404:
            return
        if r.status_code in (401, 403):
            raise RuntimeError(f"Firebase رفض الوصول ({r.status_code}) — راجع Rules أو المفتاح")
        if r.status_code != 200:
            raise RuntimeError(f"Firebase HTTP {r.status_code}: {r.text[:140]}")

    def _fb_loop(self):
        last_cmd = None
        last_state_json = ""
        last_state_at = 0.0
        pushed = {}
        last_err = ""
        while not self.stop_ev.wait(1.2):
            if not (self.fb_on and self.fb_url.strip() and len(self.code_norm) >= 12):
                self.fb_status = "معطّل"
                last_cmd = None
                pushed.clear()
                last_state_json = ""
                continue
            room = self.code_norm.lower()
            try:
                if self._is_firestore():
                    # 1) قراءة أوامر الهاتف / الويب
                    r = self._fs_req("GET", f"rooms/{room}/items/cmd")
                    self._fb_check(r, allow_404=True)
                    cmd = _fs_decode_doc(r.json()) if r.status_code == 200 else None
                    if last_cmd is None:
                        last_cmd = cmd.get("id", "") if isinstance(cmd, dict) else ""
                    elif isinstance(cmd, dict) and cmd.get("id") and cmd.get("id") != last_cmd:
                        last_cmd = cmd["id"]
                        act = cmd.get("action")
                        LAST_REMOTE[0] = time.time()
                        if act != "hb":
                            try:
                                params = json.loads(cmd.get("paramsJson") or "{}")
                            except Exception:
                                params = {}
                            res = self.handle(act, params)
                            if not (act in ("internal_gemini", "make_file_internal_gemini") and res.get("ok") and not self.app.v["gem_key"].get().strip()):
                                resp_doc = {
                                    "kind": "resp",
                                    "id": str(last_cmd)[:80],
                                    "ok": bool(res.get("ok")),
                                    "error": str(res.get("error") or "")[:1200],
                                    "name": str(res.get("name") or "")[:160],
                                    "file_ver": int(res.get("file_ver") or 0),
                                    "ts": int(time.time()),
                                }
                                self._fb_check(self._fs_req("PATCH", f"rooms/{room}/items/resp", resp_doc))

                    # 2) تحديث حالة اللوحة الأم
                    snap = dict(self.snap)
                    if snap:
                        fs_snap = {
                            "ok": 1,
                            "name": str(snap.get("name") or "PC")[:120],
                            "mt5": bool(snap.get("mt5")),
                            "conn": str(snap.get("conn") or "")[:120],
                            "busy": bool(snap.get("busy")),
                            "ai": bool(snap.get("ai")),
                            "status": str(snap.get("status") or "")[:400],
                            "price": str(snap.get("price") or "")[:240],
                            "symbol": str(snap.get("symbol") or "XAUUSD")[:40],
                            "tfsJson": json.dumps(snap.get("tfs") or {}, ensure_ascii=False)[:500],
                            "chain": bool(snap.get("chain")),
                            "provider": str(snap.get("provider") or PROV_GEMINI)[:80],
                            "gem_model": str(snap.get("gem_model") or GEMINI_DEFAULT_MODEL)[:100],
                            "claude_model": str(snap.get("claude_model") or CLAUDE_DEFAULT_MODEL)[:100],
                            "tg_mode": str(snap.get("tg_mode") or "يدوي")[:30],
                            "label": str(snap.get("label") or "")[:120],
                            "chart_active": bool(snap.get("chart_active")),
                            "chart_tf": str(snap.get("chart_tf") or "M15")[:12],
                            "versJson": json.dumps(snap.get("vers") or {}, ensure_ascii=False)[:1000],
                            "log": str(snap.get("log") or "")[:5500],
                            "ts": int(time.time()),
                        }
                        cmp_obj = dict(fs_snap)
                        cmp_obj.pop("ts", None)
                        js = json.dumps(cmp_obj, ensure_ascii=False, sort_keys=True)
                        now = time.time()
                        if js != last_state_json or now - last_state_at > 8:
                            self._fb_check(self._fs_req("PATCH", f"rooms/{room}", fs_snap))
                            last_state_json, last_state_at = js, now

                    # 3) رفع المحتويات والملفات عند تغيّر نسختها (إيقاف رفع الرسم البياني عند إيقافه لتوفير الاستهلاك)
                    for k, c in list(self.contents.items()):
                        if k == "chart" and not snap.get("chart_active"):
                            continue
                        if c["ver"] and pushed.get(k) != c["ver"]:
                            item_doc = {
                                "kind": k,
                                "name": str(c["name"])[:160],
                                "text": str(c["text"])[:700000],
                                "ver": int(c["ver"]),
                                "ts": int(time.time()),
                            }
                            self._fb_check(self._fs_req("PATCH", f"rooms/{room}/items/{k}", item_doc))
                            pushed[k] = c["ver"]
                else:
                    # وضع Realtime Database الاختياري
                    r = self._rtdb("GET", room, "cmd")
                    self._fb_check(r)
                    cmd = r.json() if r.text.strip() not in ("", "null") else None
                    if last_cmd is None:
                        last_cmd = cmd.get("id", "") if isinstance(cmd, dict) else ""
                    elif isinstance(cmd, dict) and cmd.get("id") and cmd.get("id") != last_cmd:
                        last_cmd = cmd["id"]
                        act = cmd.get("action")
                        LAST_REMOTE[0] = time.time()
                        if act != "hb":
                            res = self.handle(act, cmd.get("params") or {})
                            self._rtdb("PUT", room, "resp", {"id": last_cmd, "res": res})
                    snap = dict(self.snap)
                    js = json.dumps(snap, ensure_ascii=False, sort_keys=True)
                    now = time.time()
                    if snap and (js != last_state_json or now - last_state_at > 10):
                        snap["ts"] = int(now)
                        self._fb_check(self._rtdb("PUT", room, "state", snap))
                        last_state_json, last_state_at = js, now
                    for k, c in list(self.contents.items()):
                        if k == "chart" and not snap.get("chart_active"):
                            continue
                        if c["ver"] and pushed.get(k) != c["ver"]:
                            self._fb_check(self._rtdb("PUT", room, f"content/{k}", c))
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
        self.v = {k: tk.StringVar() for k in [
            "login", "password", "server", "symbol", "gem_key", "gem_model", "claude_key", "claude_model",
            "provider", "tg_token", "tg_chat", "tg_mode", "br_code", "br_fb_url", "br_fb_secret"
        ]}
        self.chain = tk.BooleanVar(value=False)
        self.save_keys = tk.BooleanVar(value=False)
        self.br_fb_on = tk.BooleanVar(value=True)
        self.tf_vars = {n: tk.BooleanVar(value=(n != "D1")) for n in TF_MAP}
        self.chart_active = False
        self.chart_tf = "M15"
        self.chart_candles = []
        self.chart_digits = 2
        self.chart_bid = 0.0
        self.chart_ask = 0.0
        self.chart_updated = ""
        self.chart_json = ""
        self.chart_last_push = 0.0
        self.chart_view_offset = 0
        self.chart_candle_w = 10.0
        self.chart_drag_x = None
        self.chart_drag_offset = 0
        self.chart_crosshair = None
        self.chart_stop_ev = threading.Event()
        self.chart_wake_ev = threading.Event()
        self.chart_push_remote_ev = threading.Event()
        self._build_ui()
        self._load_settings()
        self.bridge = Bridge(self)
        self.after(900, self.bridge.start)
        threading.Thread(target=self._chart_worker_loop, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self.after(1800, lambda: self.refresh_models_async(True))
        self.after(600, self.connect_async)

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
        self.b_chart = ttk.Button(bf, text="📈 عرض الرسم البياني", command=lambda: self.start_live_chart(switch_tab=True, force_remote=True))
        self.b_internal_gem = ttk.Button(bf, text="✨ إنشاء ملف ومشاركته مع جيمناي الداخلي", command=self.start_internal_gemini)
        for b in (self.b_fetch, self.b_gem, self.b_internal_gem, self.b_all, self.b_tg, self.b_tgfile, self.b_share, self.b_chart, self.b_stop):
            b.pack(side="left", padx=3)
        self.action_buttons = [self.b_connect, self.b_fetch, self.b_gem, self.b_internal_gem, self.b_all, self.b_tg, self.b_tgfile,
                               self.b_share, self.b_models]

        f4 = ttk.LabelFrame(self, text=" 4) الربط مع تطبيق الهاتف (SMC Phone) — محلي تلقائي + Firebase افتراضياً ")
        f4.pack(fill="x", padx=8, pady=3)
        self._entry(f4, "رمز الربط", "br_code", 0, 0, w=18)
        ttk.Button(f4, text="📋 نسخ", command=self.br_copy).grid(row=0, column=2, **pad)
        ttk.Button(f4, text="🔁 رمز جديد", command=self.br_newcode).grid(row=0, column=3, **pad)
        self.lbl_bridge = ttk.Label(f4, text="...", foreground="#1f4e79")
        self.lbl_bridge.grid(row=0, column=4, columnspan=4, sticky="w", **pad)
        ttk.Checkbutton(f4, text="تفعيل Firebase (افتراضي)", variable=self.br_fb_on).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        self._entry(f4, "Firebase URL", "br_fb_url", 1, 1, w=40)
        self._entry(f4, "API Key / Secret", "br_fb_secret", 1, 2, show="*", w=18)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=3)

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
        self.chart_tab = self._build_chart_tab(self.nb)
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
        c["tg_mode"] = c["tg_mode"] if c["tg_mode"] in ("يدوي", "تلقائي") else "يدوي"
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

    # ---------- symbols ----------
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
        self._fill_symbols()
        self._apply_symbol_change()

    def on_symbol_selected(self, event=None):
        self._apply_symbol_change()

    def _apply_symbol_change(self):
        sym = self.v["symbol"].get().strip() or "XAUUSD"
        set_symbol(sym)
        if self.prompt_symbol and self.prompt_symbol != sym:
            cur_prompt = self.prompt_text.get("1.0", "end").rstrip("\n")
            updated = swap_symbol_in_text(cur_prompt, self.prompt_symbol, sym)
            if updated != cur_prompt:
                self._set_box(self.prompt_text, updated)
                self.prompt_text.tag_add("rtl", "1.0", "end")
        self.prompt_symbol = sym
        if getattr(self, "chart_active", False):
            self.chart_view_offset = 0
            self.chart_push_remote_ev.set()
            self.chart_wake_ev.set()

    def _on_provider_change(self):
        prov = self.v["provider"].get()
        if prov == PROV_CLAUDE_CLI:
            exe = find_claude_cli()
            self.lbl_cli.config(
                text=("✅ Claude Code جاهز" if exe else "⚠ Claude Code غير مثبت"),
                foreground=("#1e8449" if exe else "#c0392b"),
            )
        else:
            self.lbl_cli.config(text="")

    # ---------- MT5 Connect ----------
    def connect_async(self):
        if self.busy:
            return
        c = self.cfg()
        self.set_busy(True, "🔌 جاري الاتصال بمنصة MT5...")

        def work():
            try:
                with self.mt5_lock:
                    mt5.shutdown()
                    kw = {}
                    if c["login"]:
                        try:
                            kw["login"] = int(c["login"])
                        except ValueError:
                            raise RuntimeError("رقم الحساب يجب أن يكون أرقاماً فقط.")
                    if c["password"]:
                        kw["password"] = c["password"]
                    if c["server"]:
                        kw["server"] = c["server"]
                    if not mt5.initialize(**kw):
                        raise RuntimeError(f"فشل الاتصال بـ MT5: {mt5.last_error()}")
                    ai = mt5.account_info()
                    syms = mt5.symbols_get() or []
                    names_all = sorted({s.name for s in syms})
                    names_vis = sorted({s.name for s in syms if getattr(s, "visible", False)})
                    set_symbol(c["symbol"])
                    price = get_current_price(SYMBOL)
                acc_str = f"● متصل ({ai.login} / {ai.server})" if ai else "● متصل"

                def ok():
                    self.mt5_ok = True
                    self.lbl_conn.config(text=acc_str, foreground="#1e8449")
                    self._set_symbol_lists(names_all, names_vis)
                    if price:
                        self.lbl_price.config(text=f"{SYMBOL}: {fmt_price(price)} / {fmt_price(price, 'ask')}")
                    self.set_busy(False, "✅ تم الاتصال بمنصة MT5")
                    info_ar(f"✅ تم الاتصال بـ MT5: {acc_str}")

                self.ui(ok)
            except Exception as e:
                err_msg = str(e)

                def fail():
                    self.mt5_ok = False
                    self.lbl_conn.config(text="● غير متصل", foreground="#c0392b")
                    self._fail(err_msg)

                self.ui(fail)

        threading.Thread(target=work, daemon=True).start()

    # ---------- Fetch Live Data ----------
    def start_fetch(self, then_ai=False):
        if self.busy:
            return
        tfs = [n for n, v in self.tf_vars.items() if v.get()]
        if not tfs:
            messagebox.showwarning("تنبيه", "اختر فريماً واحداً على الأقل.")
            return
        c = self.cfg()
        set_symbol(c["symbol"])
        self.set_busy(True, f"📥 جاري جلب البيانات الحية ({c['symbol']})...")

        def work():
            try:
                with self.mt5_lock:
                    if not self.mt5_ok and not mt5.initialize():
                        raise RuntimeError(f"منصة MT5 غير متصلة: {mt5.last_error()}")
                    price = get_current_price(c["symbol"])
                    rows = []
                    for i, tf_name in enumerate(tfs, 1):
                        self.status(f"📥 تحليل {c['symbol']} ({tf_name}) [{i}/{len(tfs)}]...")
                        row = analyze_timeframe(tf_name, TF_MAP[tf_name])
                        if row:
                            rows.append(row)
                if not rows:
                    raise RuntimeError("لم يتم جلب أي فريم بنجاح — تحقق من الرمز واتصال المنصة.")
                txt = rows_to_text(rows, c["symbol"], price=price)

                def ok():
                    self.mt5_ok = True
                    self.lbl_conn.config(text="● متصل", foreground="#1e8449")
                    self.data_text = txt
                    self._set_box(self.data_box, txt)
                    self.nb.select(self.data_box.master)
                    if price:
                        self.lbl_price.config(text=f"{c['symbol']}: {fmt_price(price)} / {fmt_price(price, 'ask')}")
                    self.set_busy(False, f"✅ تم جلب {len(rows)} فريمات لـ {c['symbol']}")
                    if then_ai or self.chain.get():
                        self.start_ai()

                self.ui(ok)
            except Exception as e:
                err_msg = str(e)
                self.ui(lambda: self._fail(err_msg))

        threading.Thread(target=work, daemon=True).start()

    # ---------- Request File & AI ----------
    def _prepare_file(self):
        if not self.data_text.strip():
            messagebox.showwarning("تنبيه", "اجلب البيانات الحية أولاً.")
            return None
        prompts = self.prompt_text.get("1.0", "end").strip() or default_prompts(self.cfg()["symbol"])
        sym = self.cfg()["symbol"]
        path = build_request_file(prompts, self.data_text, sym)
        self.last_file = path
        self._set_box(self.file_box, path.read_text(encoding="utf-8"))
        info_ar(f"📄 تم إنشاء الملف: {path.name}")
        return path

    def _render_answer(self, text, label):
        w = self.res_text
        w.config(state="normal")
        w.delete("1.0", "end")
        if label:
            w.insert("end", f"{label}\n{'─' * 50}\n", ("h2", "rtl"))
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("# "):
                w.insert("end", s[2:] + "\n", ("h1", "rtl"))
            elif s.startswith("## ") or s.startswith("### "):
                w.insert("end", re.sub(r'^#+\s*', '', s) + "\n", ("h2", "rtl"))
            elif "**" in line:
                parts = re.split(r'(\*\*.*?\*\*)', line)
                for p in parts:
                    if p.startswith("**") and p.endswith("**"):
                        w.insert("end", p[2:-2], ("bold", "rtl"))
                    else:
                        w.insert("end", p, ("rtl",))
                w.insert("end", "\n", ("rtl",))
            else:
                w.insert("end", line + "\n", ("rtl",))

    def start_ai(self):
        if self.busy:
            return
        c = self.cfg()
        if c["provider"] == PROV_GEMINI and not c["gem_key"]:
            messagebox.showwarning("تنبيه", "أدخل Gemini API Key أولاً.")
            return
        if c["provider"] == PROV_CLAUDE_API and not c["claude_key"]:
            messagebox.showwarning("تنبيه", "أدخل Claude API Key أولاً.")
            return
        path = self._prepare_file()
        if path is None:
            return
        self.run_id += 1
        rid = self.run_id
        tok = CancelToken()
        self.cancel_token = tok
        lbl = provider_label(c)
        self.set_busy(True, f"🤖 جاري التحليل عبر {lbl}...", ai=True)

        def work():
            try:
                ans = ask_ai(c, path, tok)
                if rid != self.run_id or tok.is_set():
                    return

                def ok():
                    self.last_answer = ans
                    self.last_label = lbl
                    self._render_answer(ans, f"التحليل ({c['symbol']}) — {lbl}")
                    self.nb.select(self.res_text.master)
                    self.set_busy(False, f"✅ اكتمل التحليل ({lbl})")
                    if c["tg_mode"] == "تلقائي" and c["tg_token"] and c["tg_chat"]:
                        self.send_telegram_async()

                self.ui(ok)
            except Cancelled:
                if rid == self.run_id:
                    self.ui(lambda: self.set_busy(False, "⏹ تم إيقاف التحليل"))
            except Exception as e:
                if rid == self.run_id:
                    err_msg = str(e)
                    self.ui(lambda: self._fail(err_msg))

        threading.Thread(target=work, daemon=True).start()

    def start_internal_gemini(self, remote_relay=False):
        if self.busy:
            return
        c = self.cfg()
        path = self._prepare_file()
        if path is None:
            return
        self.run_id += 1
        rid = self.run_id
        tok = CancelToken()
        self.cancel_token = tok
        lbl = "Gemini الداخلي (مباشر)"
        self.set_busy(True, "✨ جاري إنشاء الملف ومشاركته مع جيمناي الداخلي...", ai=True)

        def work():
            try:
                file_txt = Path(path).read_text(encoding="utf-8")
                room = norm_code(c.get("br_code") or DEFAULT_PAIR_CODE).lower()
                ans = None
                try:
                    r = http_call(
                        tok, "POST", DEFAULT_INTERNAL_AI_URL,
                        json={"content": file_txt, "symbol": c["symbol"], "roomId": room, "pushToFirebase": True},
                        timeout=120,
                    )
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if r.status_code == 200 and "application/json" in ct:
                        js = r.json()
                        if js.get("ok") and js.get("answer"):
                            ans = str(js["answer"]).strip()
                            lbl_used = str(js.get("label") or lbl)
                except Cancelled:
                    raise
                except Exception:
                    ans = None

                if not ans and c["gem_key"]:
                    ans = call_gemini(c["gem_key"], c["gem_model"], path, "اقرأ الملف", tok)
                    lbl_used = f"Gemini ({c['gem_model']})"

                if not ans:
                    if remote_relay:
                        self.ui(lambda: self.set_busy(False, "✨ تم رفع الملف — لوحة الويب ستكمل التحليل وإرسال النتيجة"))
                        return
                    raise RuntimeError(
                        "تعذر الوصول إلى نقطة Gemini الداخلية مباشرة من هذا الجهاز.\n"
                        "افتح لوحة الويب السحابية واضغط 'إنشاء ملف ومشاركته مع جيمناي الداخلي' أو أدخل Gemini API Key."
                    )

                if rid != self.run_id or tok.is_set():
                    return

                def ok():
                    self.last_answer = ans
                    self.last_label = lbl_used
                    self._render_answer(ans, f"التحليل ({c['symbol']}) — {lbl_used}")
                    self.nb.select(self.res_text.master)
                    self.set_busy(False, f"✅ اكتمل تحليل جيمناي الداخلي ({c['symbol']})")
                    self.bridge.tick(force=True)
                    if c["tg_mode"] == "تلقائي" and c["tg_token"] and c["tg_chat"]:
                        self.send_telegram_async()

                self.ui(ok)
            except Cancelled:
                if rid == self.run_id:
                    self.ui(lambda: self.set_busy(False, "⏹ تم إيقاف التحليل"))
            except Exception as e:
                if rid == self.run_id:
                    err_msg = str(e)
                    self.ui(lambda: self._fail(err_msg))

        threading.Thread(target=work, daemon=True).start()

    def stop_ai(self):
        if self.cancel_token is not None:
            self.cancel_token.cancel()
        self.set_busy(False, "⏹ تم الإيقاف")

    # ---------- Telegram & Share ----------
    def send_telegram_async(self):
        c = self.cfg()
        if not self.last_answer.strip():
            messagebox.showwarning("تنبيه", "لا توجد نتيجة تحليل لإرسالها.")
            return
        if not c["tg_token"] or not c["tg_chat"]:
            messagebox.showwarning("تنبيه", "أدخل Telegram Token و Chat ID.")
            return
        txt = clean_for_telegram(self.last_answer)

        def work():
            ok, msg = send_telegram(c["tg_token"], c["tg_chat"], txt)
            self.ui(lambda: self.lbl_status.config(
                text=(f"📨 تم الإرسال إلى Telegram ({msg})" if ok else f"❌ Telegram: {msg}")
            ))

        threading.Thread(target=work, daemon=True).start()

    def send_file_telegram_async(self):
        if self.busy:
            return
        c = self.cfg()
        if not c["tg_token"] or not c["tg_chat"]:
            messagebox.showwarning("تنبيه", "أدخل Telegram Token و Chat ID.")
            return
        path = self._prepare_file()
        if path is None:
            return
        self.set_busy(True, "📎 جاري إرسال الملف إلى Telegram...")

        def work():
            ok, msg = send_telegram_file(c["tg_token"], c["tg_chat"], path, caption=f"SMC {c['symbol']}")
            self.ui(lambda: self.set_busy(False, f"📎 تم إرسال الملف: {msg}" if ok else f"❌ Telegram: {msg}"))

        threading.Thread(target=work, daemon=True).start()

    def share_bluetooth(self):
        path = self._prepare_file()
        if path is None:
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["fsquirt.exe"], shell=False)
                self.lbl_status.config(text=f"📡 افتح نافذة البلوتوث واختر الملف: {path.name}")
            else:
                messagebox.showinfo("مشاركة", f"تم إنشاء الملف:\n{path}")
        except Exception as e:
            messagebox.showinfo("مشاركة", f"تم إنشاء الملف:\n{path}\n(تعذر فتح البلوتوث تلقائياً: {e})")

    def save_file_to_device(self):
        path = self._prepare_file()
        if path is None:
            return
        dst = filedialog.asksaveasfilename(
            title="حفظ الملف",
            initialfile=path.name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if dst:
            shutil.copy2(path, dst)
            self.lbl_status.config(text=f"💾 تم حفظ الملف: {Path(dst).name}")

    # ---------- Models ----------
    def refresh_models_async(self, silent=False):
        c = self.cfg()
        if not c["gem_key"] and not c["claude_key"]:
            if not silent:
                messagebox.showinfo("تنبيه", "أدخل Gemini API Key أو Claude API Key لتحديث القوائم.")
            return
        if not silent:
            self.set_busy(True, "🔄 جاري تحديث قوائم الموديلات...")

        def work():
            gem_list, claude_list, errs = None, None, []
            if c["gem_key"]:
                try:
                    gem_list = list_gemini_models(c["gem_key"])
                except Exception as e:
                    errs.append(f"Gemini: {e}")
            if c["claude_key"]:
                try:
                    claude_list = list_claude_models(c["claude_key"])
                except Exception as e:
                    errs.append(f"Claude: {e}")

            def apply():
                if gem_list:
                    self.cb_gem["values"] = gem_list
                if claude_list:
                    self.cb_claude["values"] = claude_list
                if not silent:
                    msg = "✅ تم تحديث الموديلات" if not errs else "⚠ " + " | ".join(errs)
                    self.set_busy(False, msg)

            self.ui(apply)

        threading.Thread(target=work, daemon=True).start()

    # ---------- Live Interactive Candlestick Chart ----------
    def _build_chart_tab(self, nb):
        fr = ttk.Frame(nb)
        nb.add(fr, text="📈 الرسم البياني المباشر")

        tb = tk.Frame(fr, bg="#0f172a", padx=8, pady=6)
        tb.pack(fill="x")

        self.btn_chart_start = tk.Button(
            tb, text="📈 عرض الرسم البياني", bg="#059669", fg="#ffffff",
            relief="flat", padx=10, pady=4, font=("Segoe UI", 9, "bold"),
            command=lambda: self.start_live_chart(switch_tab=False, force_remote=True)
        )
        self.btn_chart_start.pack(side="left", padx=3)

        self.btn_chart_stop = tk.Button(
            tb, text="⏹ إيقاف العرض", bg="#dc2626", fg="#ffffff",
            relief="flat", padx=10, pady=4, font=("Segoe UI", 9, "bold"),
            state="disabled", command=self.stop_live_chart
        )
        self.btn_chart_stop.pack(side="left", padx=3)

        tk.Frame(tb, width=1, bg="#334155").pack(side="left", fill="y", padx=6)

        self.chart_tf_btns = {}
        for tf_name in TF_MAP:
            b = tk.Button(
                tb, text=tf_name, bg="#1e293b", fg="#cbd5e1",
                relief="flat", padx=8, pady=3, font=("Consolas", 9, "bold"),
                command=lambda t=tf_name: self.set_chart_timeframe(t, force_remote=True)
            )
            b.pack(side="left", padx=2)
            self.chart_tf_btns[tf_name] = b

        tk.Frame(tb, width=1, bg="#334155").pack(side="left", fill="y", padx=6)

        for lbl, cmd in (
            ("🔍+", lambda: self._chart_zoom(1.25)),
            ("🔍-", lambda: self._chart_zoom(0.8)),
            ("↺ أحدث شمعة", self._chart_reset_view),
        ):
            tk.Button(
                tb, text=lbl, bg="#1e293b", fg="#e2e8f0",
                relief="flat", padx=8, pady=3, font=("Segoe UI", 9),
                command=cmd
            ).pack(side="left", padx=2)

        self.lbl_chart_state = tk.Label(
            tb, text="⏹ متوقف", bg="#0f172a", fg="#94a3b8", font=("Segoe UI", 9, "bold")
        )
        self.lbl_chart_state.pack(side="right", padx=8)

        hud = tk.Frame(fr, bg="#111827", padx=10, pady=4)
        hud.pack(fill="x")
        self.lbl_chart_hud = tk.Label(
            hud,
            text="اضغط 'عرض الرسم البياني' لنقل الشموع الحية من MT5 مباشرة — اسحب للتحريك، وبكرة الفأرة للتكبير/التصغير",
            bg="#111827", fg="#38bdf8", font=("Consolas", 9), anchor="w"
        )
        self.lbl_chart_hud.pack(fill="x")

        self.chart_canvas = tk.Canvas(fr, bg="#0b1220", highlightthickness=0, cursor="crosshair")
        self.chart_canvas.pack(fill="both", expand=True)
        self.chart_canvas.bind("<Configure>", lambda e: self._draw_chart())
        self.chart_canvas.bind("<ButtonPress-1>", self._on_chart_press)
        self.chart_canvas.bind("<B1-Motion>", self._on_chart_drag)
        self.chart_canvas.bind("<ButtonRelease-1>", self._on_chart_release)
        self.chart_canvas.bind("<Motion>", self._on_chart_motion)
        self.chart_canvas.bind("<Leave>", self._on_chart_leave)
        self.chart_canvas.bind("<MouseWheel>", self._on_chart_wheel)
        self.chart_canvas.bind("<Button-4>", lambda e: self._chart_zoom(1.18))
        self.chart_canvas.bind("<Button-5>", lambda e: self._chart_zoom(0.85))
        self._update_chart_tf_buttons()
        return fr

    def _update_chart_tf_buttons(self):
        if not hasattr(self, "chart_tf_btns"):
            return
        for tf_name, btn in self.chart_tf_btns.items():
            active = (tf_name == self.chart_tf)
            btn.config(
                bg=("#0284c7" if active else "#1e293b"),
                fg=("#ffffff" if active else "#cbd5e1"),
            )
        if hasattr(self, "btn_chart_start"):
            self.btn_chart_start.config(state=("disabled" if self.chart_active else "normal"))
            self.btn_chart_stop.config(state=("normal" if self.chart_active else "disabled"))
            if self.chart_active:
                sym = self.v["symbol"].get().strip() or SYMBOL
                self.lbl_chart_state.config(
                    text=f"🟢 مباشر • {sym} • {self.chart_tf}", fg="#34d399"
                )
            else:
                self.lbl_chart_state.config(text="⏹ متوقف (توفير الاستهلاك)", fg="#94a3b8")

    def start_live_chart(self, tf=None, switch_tab=False, force_remote=True):
        if tf and tf in TF_MAP:
            self.chart_tf = tf
        self.chart_active = True
        self.chart_view_offset = 0
        if force_remote:
            self.chart_push_remote_ev.set()
        self.chart_wake_ev.set()
        self._update_chart_tf_buttons()
        if switch_tab and hasattr(self, "chart_tab"):
            self.nb.select(self.chart_tab)
        self.lbl_status.config(text=f"📈 تم تشغيل الرسم البياني المباشر ({self.chart_tf})")
        info_ar(f"📈 بدء عرض الرسم البياني المباشر ({self.v['symbol'].get().strip() or SYMBOL} / {self.chart_tf})")

    def stop_live_chart(self):
        self.chart_active = False
        self.chart_wake_ev.set()
        self._update_chart_tf_buttons()
        self.lbl_status.config(text="⏹ تم إيقاف الرسم البياني وتوفير الاستهلاك")
        info_ar("⏹ تم إيقاف نقل وعرض الرسم البياني")

    def set_chart_timeframe(self, tf, force_remote=True):
        if tf not in TF_MAP:
            return
        self.chart_tf = tf
        self.chart_view_offset = 0
        self._update_chart_tf_buttons()
        if self.chart_active:
            if force_remote:
                self.chart_push_remote_ev.set()
            self.chart_wake_ev.set()
        else:
            self.start_live_chart(tf=tf, switch_tab=False, force_remote=force_remote)

    def refresh_live_chart_once(self):
        self.chart_push_remote_ev.set()
        if not self.chart_active:
            self.start_live_chart(switch_tab=False, force_remote=True)
        else:
            self.chart_wake_ev.set()

    def _chart_zoom(self, factor):
        self.chart_candle_w = max(4.0, min(38.0, self.chart_candle_w * factor))
        self._draw_chart()

    def _chart_reset_view(self):
        self.chart_view_offset = 0
        self.chart_candle_w = 10.0
        self._draw_chart()

    def _on_chart_press(self, event):
        self.chart_drag_x = event.x
        self.chart_drag_offset = self.chart_view_offset

    def _on_chart_drag(self, event):
        if self.chart_drag_x is None or not self.chart_candles:
            return
        dx = event.x - self.chart_drag_x
        shift = int(round(dx / max(4.0, self.chart_candle_w)))
        max_off = max(0, len(self.chart_candles) - 8)
        self.chart_view_offset = max(0, min(max_off, self.chart_drag_offset + shift))
        self.chart_crosshair = (event.x, event.y)
        self._draw_chart()

    def _on_chart_release(self, event):
        self.chart_drag_x = None

    def _on_chart_motion(self, event):
        self.chart_crosshair = (event.x, event.y)
        self._draw_chart()

    def _on_chart_leave(self, event):
        self.chart_crosshair = None
        self._draw_chart()

    def _on_chart_wheel(self, event):
        factor = 1.18 if getattr(event, "delta", 0) > 0 else 0.85
        self._chart_zoom(factor)

    def _chart_worker_loop(self):
        while not self.chart_stop_ev.is_set():
            if not self.chart_active:
                self.chart_wake_ev.wait(0.8)
                self.chart_wake_ev.clear()
                continue
            self.chart_wake_ev.clear()
            sym = (self.v["symbol"].get().strip() or SYMBOL)
            tf_name = self.chart_tf if self.chart_tf in TF_MAP else "M15"
            acquired = self.mt5_lock.acquire(timeout=0.35)
            if acquired:
                try:
                    if not self.mt5_ok:
                        mt5.initialize()
                    mt5.symbol_select(sym, True)
                    rates = mt5.copy_rates_from_pos(sym, TF_MAP[tf_name], 0, 260)
                    info = mt5.symbol_info(sym)
                    digits = int(getattr(info, "digits", 2) or 2) if info else (2 if ("XAU" in sym.upper() or "JPY" in sym.upper()) else 5)
                    tick = mt5.symbol_info_tick(sym)
                    bid = float(tick.bid) if tick else 0.0
                    ask = float(tick.ask) if tick else 0.0
                    if rates is not None and len(rates) > 0:
                        candles = [
                            [
                                int(r["time"]),
                                round(float(r["open"]), digits),
                                round(float(r["high"]), digits),
                                round(float(r["low"]), digits),
                                round(float(r["close"]), digits),
                                int(r["tick_volume"]),
                            ]
                            for r in rates
                        ]
                        if bid <= 0:
                            bid = float(candles[-1][4])
                        if ask <= 0:
                            ask = bid
                        now_str = datetime.now(SAUDI_TZ).strftime("%H:%M:%S")
                        now_ts = time.time()
                        force_push = self.chart_push_remote_ev.is_set()
                        need_remote = force_push or (now_ts - self.chart_last_push >= CHART_REMOTE_INTERVAL) or (not self.chart_json)
                        payload_json = self.chart_json
                        if need_remote:
                            self.chart_push_remote_ev.clear()
                            self.chart_last_push = now_ts
                            payload_json = json.dumps({
                                "symbol": sym,
                                "tf": tf_name,
                                "digits": digits,
                                "bid": round(bid, digits),
                                "ask": round(ask, digits),
                                "updated": now_str,
                                "candles": candles[-180:],
                            }, ensure_ascii=False, separators=(",", ":"))

                        def apply_chart(c=candles, d=digits, b=bid, a=ask, u=now_str, pj=payload_json, tf_u=tf_name, s_u=sym, nr=need_remote):
                            if not self.chart_active:
                                return
                            self.mt5_ok = True
                            self.chart_candles = c
                            self.chart_digits = d
                            self.chart_bid = b
                            self.chart_ask = a
                            self.chart_updated = u
                            if nr:
                                self.chart_json = pj
                            self.lbl_price.config(text=f"{s_u}: {b:.{d}f} / {a:.{d}f}")
                            self._update_chart_tf_buttons()
                            self._draw_chart()

                        self.ui(apply_chart)
                except Exception as e:
                    logger.error("chart worker: %s", e)
                finally:
                    self.mt5_lock.release()
            self.chart_wake_ev.wait(3.0)

    def _draw_chart(self):
        if not hasattr(self, "chart_canvas"):
            return
        cv = self.chart_canvas
        w = max(1, cv.winfo_width())
        h = max(1, cv.winfo_height())
        cv.delete("all")

        candles = self.chart_candles
        if not candles:
            cv.create_text(
                w / 2, h / 2,
                text="اضغط '📈 عرض الرسم البياني' لجلب وعرض الشموع المباشرة من MT5",
                fill="#64748b", font=("Segoe UI", 12, "bold")
            )
            return

        pad_l, pad_t, pad_r, pad_b = 14, 16, 78, 28
        plot_w = max(40, w - pad_l - pad_r)
        plot_h = max(40, h - pad_t - pad_b)
        step = max(4.0, float(self.chart_candle_w))
        visible_count = max(8, int(plot_w // step))

        total = len(candles)
        end_idx = max(1, total - int(self.chart_view_offset))
        start_idx = max(0, end_idx - visible_count)
        vis = candles[start_idx:end_idx]
        if not vis:
            return

        hi = max(c[2] for c in vis)
        lo = min(c[3] for c in vis)
        if self.chart_bid > 0 and self.chart_view_offset == 0:
            hi = max(hi, self.chart_bid)
            lo = min(lo, self.chart_bid)
        rng = hi - lo
        if rng <= 0:
            rng = max(abs(hi) * 0.001, 0.01)
        pad_p = rng * 0.08
        p_max = hi + pad_p
        p_min = lo - pad_p
        p_rng = max(1e-9, p_max - p_min)

        def y_of(price):
            return pad_t + (p_max - price) / p_rng * plot_h

        digits = self.chart_digits

        # Grid & Price Axis
        for i in range(6):
            frac = i / 5.0
            yy = pad_t + frac * plot_h
            pval = p_max - frac * p_rng
            cv.create_line(pad_l, yy, w - pad_r, yy, fill="#1e293b", dash=(2, 4))
            cv.create_text(w - pad_r + 6, yy, text=f"{pval:.{digits}f}", fill="#94a3b8",
                           font=("Consolas", 8), anchor="w")

        cv.create_line(w - pad_r, pad_t, w - pad_r, h - pad_b, fill="#334155")
        cv.create_line(pad_l, h - pad_b, w - pad_r, h - pad_b, fill="#334155")

        body_w = max(2.0, step * 0.66)
        label_every = max(1, len(vis) // 6)
        for i, c in enumerate(vis):
            cx = pad_l + (i + 0.5) * step
            if cx > w - pad_r - 2:
                break
            ts_sec, op, ch, cl, cc, vol = c
            y_hi = y_of(ch)
            y_lo = y_of(cl)
            y_op = y_of(op)
            y_cl = y_of(cc)
            bull = cc >= op
            col = "#10b981" if bull else "#ef4444"
            cv.create_line(cx, y_hi, cx, y_lo, fill=col, width=1)
            top_y = min(y_op, y_cl)
            bot_y = max(y_op, y_cl)
            if bot_y - top_y < 1.5:
                bot_y = top_y + 1.5
            cv.create_rectangle(cx - body_w / 2.0, top_y, cx + body_w / 2.0, bot_y,
                                fill=col, outline=col)

            if i % label_every == 0:
                dt_lbl = datetime.fromtimestamp(ts_sec, tz=SAUDI_TZ).strftime(
                    "%m-%d" if self.chart_tf in ("H4", "D1") else "%H:%M"
                )
                cv.create_line(cx, pad_t, cx, h - pad_b, fill="#141e33")
                cv.create_text(cx, h - pad_b + 12, text=dt_lbl, fill="#94a3b8", font=("Consolas", 8))

        # Live Bid Price Line
        if self.chart_bid > 0 and p_min <= self.chart_bid <= p_max:
            yb = y_of(self.chart_bid)
            cv.create_line(pad_l, yb, w - pad_r, yb, fill="#38bdf8", dash=(4, 3), width=1)
            cv.create_rectangle(w - pad_r + 2, yb - 9, w - 2, yb + 9, fill="#0284c7", outline="")
            cv.create_text(w - pad_r + 6, yb, text=f"{self.chart_bid:.{digits}f}",
                           fill="#ffffff", font=("Consolas", 8, "bold"), anchor="w")

        # Crosshair & HUD
        sel = vis[-1]
        if self.chart_crosshair is not None:
            mx, my = self.chart_crosshair
            if pad_l <= mx <= w - pad_r and pad_t <= my <= h - pad_b:
                idx = int((mx - pad_l) / step)
                if 0 <= idx < len(vis):
                    sel = vis[idx]
                    sx = pad_l + (idx + 0.5) * step
                    cv.create_line(sx, pad_t, sx, h - pad_b, fill="#475569", dash=(3, 3))
                cv.create_line(pad_l, my, w - pad_r, my, fill="#475569", dash=(3, 3))
                hp = p_max - ((my - pad_t) / plot_h) * p_rng
                cv.create_rectangle(w - pad_r + 2, my - 8, w - 2, my + 8, fill="#334155", outline="")
                cv.create_text(w - pad_r + 6, my, text=f"{hp:.{digits}f}",
                               fill="#e2e8f0", font=("Consolas", 8), anchor="w")

        sym = self.v["symbol"].get().strip() or SYMBOL
        t_str = datetime.fromtimestamp(sel[0], tz=SAUDI_TZ).strftime("%Y-%m-%d %H:%M")
        self.lbl_chart_hud.config(
            text=(f"{sym} ({self.chart_tf})  |  {t_str}  |  "
                  f"O:{sel[1]:.{digits}f}  H:{sel[2]:.{digits}f}  L:{sel[3]:.{digits}f}  C:{sel[4]:.{digits}f}  "
                  f"Vol:{sel[5]}  |  Bid:{self.chart_bid:.{digits}f} / Ask:{self.chart_ask:.{digits}f}  ({self.chart_updated})")
        )

    # ---------- Settings ----------
    def save_settings(self):
        c = self.cfg()
        data = {
            "symbol": c["symbol"],
            "provider": c["provider"],
            "gem_model": c["gem_model"],
            "claude_model": c["claude_model"],
            "tg_mode": c["tg_mode"],
            "chain": bool(self.chain.get()),
            "save_keys": bool(self.save_keys.get()),
            "tfs": {n: bool(v.get()) for n, v in self.tf_vars.items()},
            "prompts": self.prompt_text.get("1.0", "end").rstrip("\n"),
            "br_code": c["br_code"],
            "br_fb_on": bool(self.br_fb_on.get()),
            "br_fb_url": c["br_fb_url"] or DEFAULT_FB_URL,
            "br_fb_secret": c["br_fb_secret"] or DEFAULT_FB_API_KEY,
            "chart_tf": self.chart_tf,
        }
        if self.save_keys.get():
            for k in ("login", "password", "server", "gem_key", "claude_key", "tg_token", "tg_chat"):
                data[k] = c[k]
        try:
            SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.lbl_status.config(text="💾 تم حفظ الإعدادات")
        except Exception as e:
            error_ar(f"❌ تعذر حفظ الإعدادات: {e}")

    def _load_settings(self):
        d = {}
        if SETTINGS_PATH.exists():
            try:
                d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except Exception:
                d = {}
        self.v["symbol"].set(d.get("symbol") or "XAUUSD")
        self.v["provider"].set(d.get("provider") if d.get("provider") in PROVIDERS else PROV_GEMINI)
        self.v["gem_model"].set(d.get("gem_model") or GEMINI_DEFAULT_MODEL)
        self.v["claude_model"].set(d.get("claude_model") or CLAUDE_DEFAULT_MODEL)
        self.v["tg_mode"].set(d.get("tg_mode") if d.get("tg_mode") in ("يدوي", "تلقائي") else "يدوي")
        self.v["br_code"].set(d.get("br_code") or DEFAULT_PAIR_CODE)
        self.v["br_fb_url"].set(d.get("br_fb_url") or DEFAULT_FB_URL)
        self.v["br_fb_secret"].set(d.get("br_fb_secret") or DEFAULT_FB_API_KEY)
        self.br_fb_on.set(bool(d.get("br_fb_on", True)))
        if d.get("chart_tf") in TF_MAP:
            self.chart_tf = d["chart_tf"]
            self._update_chart_tf_buttons()
        self.chain.set(bool(d.get("chain", False)))
        self.save_keys.set(bool(d.get("save_keys", False)))
        for k in ("login", "password", "server", "gem_key", "claude_key", "tg_token", "tg_chat"):
            if d.get(k):
                self.v[k].set(d[k])
        tfs = d.get("tfs")
        if isinstance(tfs, dict):
            for n, val in tfs.items():
                if n in self.tf_vars:
                    self.tf_vars[n].set(bool(val))
        sym = self.v["symbol"].get()
        self.prompt_symbol = sym
        prompts = d.get("prompts") or default_prompts(sym)
        self._set_box(self.prompt_text, prompts)
        self.prompt_text.tag_add("rtl", "1.0", "end")
        self._on_provider_change()

    def on_close(self):
        try:
            self.chart_active = False
            self.chart_stop_ev.set()
            self.chart_wake_ev.set()
        except Exception:
            pass
        try:
            if self.cancel_token is not None:
                self.cancel_token.cancel()
        except Exception:
            pass
        try:
            self.bridge.stop()
        except Exception:
            pass
        try:
            self.save_settings()
        except Exception:
            pass
        try:
            mt5.shutdown()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
