import { useEffect, useMemo, useRef, useState } from 'react';
import { Play, RefreshCw, RotateCcw, Square, ZoomIn, ZoomOut } from 'lucide-react';

export interface ChartPayload {
  symbol: string;
  tf: string;
  digits: number;
  bid: number;
  ask: number;
  updated: string;
  candles: [number, number, number, number, number, number][];
}

interface LiveCandleChartProps {
  payload: ChartPayload | null;
  chartActive: boolean;
  selectedTf: string;
  countdownSec: number;
  timeframes: readonly string[];
  onStart: () => void;
  onStop: () => void;
  onSelectTf: (tf: string) => void;
  onRefreshNow: () => void;
}

export default function LiveCandleChart({
  payload,
  chartActive,
  selectedTf,
  countdownSec,
  timeframes,
  onStart,
  onStop,
  onSelectTf,
  onRefreshNow,
}: LiveCandleChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [candleWidth, setCandleWidth] = useState<number>(10);
  const [viewOffset, setViewOffset] = useState<number>(0);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ x: number; offset: number } | null>(null);

  const candles = payload?.candles || [];
  const digits = Math.max(0, Math.min(6, payload?.digits ?? 2));
  const bid = payload?.bid ?? 0;
  const ask = payload?.ask ?? 0;

  const visibleSlice = useMemo(() => {
    if (!candles.length) return { vis: [], startIdx: 0 };
    const endIdx = Math.max(1, candles.length - viewOffset);
    const estCount = Math.max(12, Math.floor(820 / Math.max(4, candleWidth)));
    const startIdx = Math.max(0, endIdx - estCount);
    return { vis: candles.slice(startIdx, endIdx), startIdx };
  }, [candles, viewOffset, candleWidth]);

  const hoveredCandle = useMemo(() => {
    if (!candles.length) return null;
    if (!hoverPos || !canvasRef.current) return candles[candles.length - 1];
    const padL = 14;
    const idx = Math.floor((hoverPos.x - padL) / Math.max(4, candleWidth));
    if (idx >= 0 && idx < visibleSlice.vis.length) return visibleSlice.vis[idx];
    return candles[candles.length - 1];
  }, [candles, hoverPos, candleWidth, visibleSlice]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(320, Math.floor(rect.width));
      const h = Math.max(320, Math.floor(rect.height));
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      ctx.fillStyle = '#0B1120';
      ctx.fillRect(0, 0, w, h);

      if (!candles.length) {
        ctx.fillStyle = '#64748B';
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('اضغط "عرض الرسم البياني" لنقل الشموع الحية من MT5 مباشرة', w / 2, h / 2);
        return;
      }

      const padL = 14;
      const padT = 16;
      const padR = 76;
      const padB = 26;
      const plotW = Math.max(40, w - padL - padR);
      const plotH = Math.max(40, h - padT - padB);
      const step = Math.max(4, candleWidth);
      const visCount = Math.max(8, Math.floor(plotW / step));
      const endIdx = Math.max(1, candles.length - viewOffset);
      const startIdx = Math.max(0, endIdx - visCount);
      const vis = candles.slice(startIdx, endIdx);
      if (!vis.length) return;

      let hi = Math.max(...vis.map((c) => c[2]));
      let lo = Math.min(...vis.map((c) => c[3]));
      if (bid > 0 && viewOffset === 0) {
        hi = Math.max(hi, bid);
        lo = Math.min(lo, bid);
      }
      let rng = hi - lo;
      if (rng <= 0) rng = Math.max(Math.abs(hi) * 0.001, 0.01);
      const pMax = hi + rng * 0.08;
      const pMin = lo - rng * 0.08;
      const pRng = Math.max(1e-9, pMax - pMin);
      const yOf = (p: number) => padT + ((pMax - p) / pRng) * plotH;

      // Grid + Price labels
      ctx.font = '11px monospace';
      ctx.textAlign = 'left';
      for (let i = 0; i <= 5; i++) {
        const frac = i / 5;
        const yy = padT + frac * plotH;
        const pv = pMax - frac * pRng;
        ctx.strokeStyle = '#1E293B';
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(padL, yy);
        ctx.lineTo(w - padR, yy);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#94A3B8';
        ctx.fillText(pv.toFixed(digits), w - padR + 6, yy + 3);
      }

      ctx.strokeStyle = '#334155';
      ctx.beginPath();
      ctx.moveTo(w - padR, padT);
      ctx.lineTo(w - padR, h - padB);
      ctx.lineTo(padL, h - padB);
      ctx.stroke();

      const bodyW = Math.max(2, step * 0.64);
      const lblEvery = Math.max(1, Math.floor(vis.length / 6));
      vis.forEach((c, i) => {
        const cx = padL + (i + 0.5) * step;
        if (cx > w - padR - 2) return;
        const bull = c[4] >= c[1];
        const col = bull ? '#10B981' : '#EF4444';
        ctx.strokeStyle = col;
        ctx.fillStyle = col;
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        ctx.moveTo(cx, yOf(c[2]));
        ctx.lineTo(cx, yOf(c[3]));
        ctx.stroke();

        const topY = Math.min(yOf(c[1]), yOf(c[4]));
        const botY = Math.max(Math.max(yOf(c[1]), yOf(c[4])), topY + 1.5);
        ctx.fillRect(cx - bodyW / 2, topY, bodyW, botY - topY);

        if (i % lblEvery === 0) {
          const dt = new Date(c[0] * 1000);
          const lbl =
            selectedTf === 'H4' || selectedTf === 'D1'
              ? `${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
              : `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
          ctx.fillStyle = '#94A3B8';
          ctx.textAlign = 'center';
          ctx.fillText(lbl, cx, h - 8);
        }
      });

      // Live Bid line
      if (bid > 0 && bid >= pMin && bid <= pMax) {
        const yb = yOf(bid);
        ctx.strokeStyle = '#38BDF8';
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(padL, yb);
        ctx.lineTo(w - padR, yb);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#0284C7';
        ctx.fillRect(w - padR + 2, yb - 9, padR - 4, 18);
        ctx.fillStyle = '#FFFFFF';
        ctx.textAlign = 'left';
        ctx.fillText(bid.toFixed(digits), w - padR + 6, yb + 4);
      }

      // Crosshair
      if (hoverPos && hoverPos.x >= padL && hoverPos.x <= w - padR && hoverPos.y >= padT && hoverPos.y <= h - padB) {
        const idx = Math.min(vis.length - 1, Math.max(0, Math.floor((hoverPos.x - padL) / step)));
        const sx = padL + (idx + 0.5) * step;
        ctx.strokeStyle = '#64748B';
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(sx, padT);
        ctx.lineTo(sx, h - padB);
        ctx.moveTo(padL, hoverPos.y);
        ctx.lineTo(w - padR, hoverPos.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    };

    draw();
    window.addEventListener('resize', draw);
    return () => window.removeEventListener('resize', draw);
  }, [candles, digits, bid, candleWidth, viewOffset, hoverPos, selectedTf]);

  const formatTime = (sec: number) => {
    const d = new Date(sec * 1000);
    return `${d.toISOString().slice(0, 10)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  };

  return (
    <section className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3 text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onStart}
            disabled={chartActive}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            <span>عرض الرسم البياني</span>
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={!chartActive}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-rose-600 text-white rounded-lg hover:bg-rose-500 disabled:opacity-50"
          >
            <Square className="w-3.5 h-3.5" />
            <span>إيقاف عرض الرسم البياني</span>
          </button>
          <button
            type="button"
            onClick={onRefreshNow}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-sky-700 text-white rounded-lg hover:bg-sky-600"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>تحديث الآن</span>
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5" dir="ltr">
          {timeframes.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onSelectTf(tf)}
              className={`px-2.5 py-1.5 text-xs font-mono-num rounded-md transition-colors ${
                selectedTf === tf
                  ? 'bg-sky-600 text-white font-semibold'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setCandleWidth((w) => Math.min(36, w * 1.25))}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-md"
            title="تكبير"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setCandleWidth((w) => Math.max(4, w * 0.8))}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-md"
            title="تصغير"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setViewOffset(0);
              setCandleWidth(10);
            }}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-md"
            title="أحدث شمعة"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs bg-slate-900 border border-slate-800 rounded-lg px-3 py-2">
        <div className="font-mono-num text-sky-400" dir="ltr">
          {hoveredCandle ? (
            <span>
              {payload?.symbol} ({payload?.tf || selectedTf}) | {formatTime(hoveredCandle[0])} | O:{hoveredCandle[1].toFixed(digits)} H:{hoveredCandle[2].toFixed(digits)} L:{hoveredCandle[3].toFixed(digits)} C:{hoveredCandle[4].toFixed(digits)} | Bid:{bid.toFixed(digits)} / Ask:{ask.toFixed(digits)}
            </span>
          ) : (
            <span>اسحب للتحريك، واستخدم عجلة الفأرة للتكبير والتصغير</span>
          )}
        </div>
        <div className={chartActive ? 'text-emerald-400 font-medium' : 'text-slate-400'}>
          {chartActive
            ? `بث مباشر • تحديث تلقائي كل 60 ثانية (المتبقي: ${countdownSec}ث)`
            : 'متوقف — لا يتم نقل بيانات (توفير الاستهلاك)'}
        </div>
      </div>

      <div className="w-full h-[460px] rounded-lg overflow-hidden border border-slate-800">
        <canvas
          ref={canvasRef}
          className="w-full h-full cursor-crosshair block"
          onMouseDown={(e) => {
            dragRef.current = { x: e.clientX, offset: viewOffset };
          }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
            if (dragRef.current) {
              const dx = e.clientX - dragRef.current.x;
              const shift = Math.round(dx / Math.max(4, candleWidth));
              const maxOff = Math.max(0, candles.length - 8);
              setViewOffset(Math.max(0, Math.min(maxOff, dragRef.current.offset + shift)));
            }
          }}
          onMouseUp={() => {
            dragRef.current = null;
          }}
          onMouseLeave={() => {
            dragRef.current = null;
            setHoverPos(null);
          }}
          onWheel={(e) => {
            e.preventDefault();
            setCandleWidth((w) => Math.max(4, Math.min(36, w * (e.deltaY < 0 ? 1.15 : 0.87))));
          }}
        />
      </div>
    </section>
  );
}
