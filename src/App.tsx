import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  Cloud,
  Copy,
  Download,
  FileCode2,
  FileText,
  FolderArchive,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Square,
  Terminal,
  Wifi,
  Zap,
} from 'lucide-react';
import {
  DEFAULT_PAIR_CODE,
  FIREBASE_META,
  pairCodeToRoomId,
  sendRoomCommand,
  subscribeRoomItem,
  subscribeRoomState,
  type RoomState,
} from './firebase';
import {
  downloadMainActivityKt,
  downloadPythonScript,
  downloadAndroidGitHubZip,
  downloadTextAsset,
  EXPORT_PREVIEWS,
} from './utils/exportStudio';

import LiveCandleChart, { type ChartPayload } from './components/LiveCandleChart';

type WorkspaceTab = 'control' | 'chart' | 'files' | 'answer' | 'export';

const TF_LIST = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'] as const;
const DEFAULT_PROVIDERS = ['Gemini', 'Claude (عبر API)', 'Claude Code (مباشر بدون API)'];
const DEFAULT_GEM_MODELS = ['gemini-flash-latest', 'gemini-pro-latest', 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'];
const DEFAULT_CLAUDE_MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5', 'claude-sonnet-4-5'];
const DEFAULT_TG_MODES = ['يدوي', 'تلقائي'];

interface ListsPayload {
  symbols?: string[];
  providers?: string[];
  gem_models?: string[];
  claude_models?: string[];
  tg_modes?: string[];
  presets?: string[];
}

export default function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('control');
  const roomId = useMemo(() => pairCodeToRoomId(DEFAULT_PAIR_CODE), []);

  const [roomState, setRoomState] = useState<RoomState | null>(null);
  const [dataItem, setDataItem] = useState<{ name: string; text: string; ver: number }>({ name: 'SMC_data.txt', text: '', ver: 0 });
  const [fileItem, setFileItem] = useState<{ name: string; text: string; ver: number }>({ name: 'SMC_request.txt', text: '', ver: 0 });
  const [answerItem, setAnswerItem] = useState<{ name: string; text: string; ver: number }>({ name: 'SMC_answer.txt', text: '', ver: 0 });
  const [promptDraft, setPromptDraft] = useState<string>('');
  const [lists, setLists] = useState<ListsPayload>({});
  const [selectedPreset, setSelectedPreset] = useState<string>('');

  const [symbol, setSymbol] = useState<string>('XAUUSD');
  const [tfs, setTfs] = useState<Record<string, boolean>>({
    M1: true, M5: true, M15: true, M30: true, H1: true, H4: true, D1: false,
  });
  const [chain, setChain] = useState<boolean>(false);
  const [provider, setProvider] = useState<string>('Gemini');
  const [gemModel, setGemModel] = useState<string>('gemini-flash-latest');
  const [claudeModel, setClaudeModel] = useState<string>('claude-sonnet-5-5');
  const [tgMode, setTgMode] = useState<string>('يدوي');

  const [toastMsg, setToastMsg] = useState<string>('');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [isExportingZip, setIsExportingZip] = useState<boolean>(false);
  const [workflowRunning, setWorkflowRunning] = useState<boolean>(false);
  const [chartActive, setChartActive] = useState<boolean>(false);
  const [chartTf, setChartTf] = useState<string>('M15');
  const [chartPayload, setChartPayload] = useState<ChartPayload | null>(null);
  const [chartCountdown, setChartCountdown] = useState<number>(60);
  const chartSyncLockUntilRef = useRef<number>(0);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg((cur) => (cur === msg ? '' : cur)), 3500);
  };

  useEffect(() => {
    setErrorMsg('');
    const unsubs = [
      subscribeRoomState(
        roomId,
        (st) => {
          setRoomState(st);
          if (st) {
            setSymbol(st.symbol || 'XAUUSD');
            if (st.tfs && Object.keys(st.tfs).length > 0) setTfs(st.tfs);
            setChain(Boolean(st.chain));
            if (st.provider) setProvider(st.provider);
            if (st.gem_model) setGemModel(st.gem_model);
            if (st.claude_model) setClaudeModel(st.claude_model);
            if (st.tg_mode) setTgMode(st.tg_mode);
            if (Date.now() > chartSyncLockUntilRef.current) {
              if (typeof st.chart_active === 'boolean') setChartActive(st.chart_active);
              if (st.chart_tf) setChartTf(st.chart_tf);
            }
          }
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'data',
        (d) => {
          if (d) setDataItem({ name: String(d.name ?? 'SMC_data.txt'), text: String(d.text ?? ''), ver: Number(d.ver ?? 0) });
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'file',
        (d) => {
          if (d) setFileItem({ name: String(d.name ?? 'SMC_request.txt'), text: String(d.text ?? ''), ver: Number(d.ver ?? 0) });
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'answer',
        (d) => {
          if (d) setAnswerItem({ name: String(d.name ?? 'SMC_answer.txt'), text: String(d.text ?? ''), ver: Number(d.ver ?? 0) });
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'prompt',
        (d) => {
          if (d && typeof d.text === 'string') setPromptDraft(d.text);
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'lists',
        (d) => {
          if (d && typeof d.text === 'string') {
            try {
              setLists(JSON.parse(d.text) as ListsPayload);
            } catch {
              // ignore malformed lists
            }
          }
        },
        (err) => setErrorMsg(err)
      ),
      subscribeRoomItem(
        roomId,
        'chart',
        (d) => {
          if (d && typeof d.text === 'string' && d.text.trim()) {
            try {
              const parsed = JSON.parse(d.text) as ChartPayload;
              if (Array.isArray(parsed.candles)) setChartPayload(parsed);
            } catch {
              // ignore malformed chart
            }
          }
        },
        (err) => setErrorMsg(err)
      ),
    ];
    return () => {
      unsubs.forEach((u) => u());
    };
  }, [roomId]);

  useEffect(() => {
    if (!chartActive) {
      setChartCountdown(60);
      return;
    }
    const timer = window.setInterval(() => {
      setChartCountdown((prev) => {
        if (prev <= 1) {
          void sendRoomCommand(roomId, 'chart_refresh', { tf: chartTf });
          return 60;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [chartActive, chartTf, roomId]);

  const currentParams = () => ({
    symbol,
    tfs,
    chain,
    provider,
    gem_model: gemModel,
    claude_model: claudeModel,
    tg_mode: tgMode,
  });

  const dispatchCommand = async (action: string, params: Record<string, unknown> = {}) => {
    setErrorMsg('');
    try {
      await sendRoomCommand(roomId, action, params);
      if (action !== 'set') showToast(`تم إرسال الأمر (${action}) عبر Firebase`);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const runFetchCreateDownload = async () => {
    setWorkflowRunning(true);
    try {
      await sendRoomCommand(roomId, 'fetch', currentParams());
      showToast('جاري جلب البيانات الحية وإنشاء الملف...');
      await new Promise((r) => setTimeout(r, 2500));
      await sendRoomCommand(roomId, 'make_file', currentParams());
      showToast('تم إرسال طلب جلب البيانات وإنشاء الملف — سيظهر الملف تلقائياً في تبويب البيانات والملف');
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setWorkflowRunning(false);
    }
  };

  const handleCopy = async (text: string, label: string) => {
    if (!text) return;
    await navigator.clipboard.writeText(text);
    showToast(`تم نسخ ${label}`);
  };

  const handleZipDownload = async () => {
    setIsExportingZip(true);
    try {
      await downloadAndroidGitHubZip();
      showToast('تم تحميل SMC-Phone-GitHub-APK.zip بنجاح');
    } finally {
      setIsExportingZip(false);
    }
  };

  const symbolsList = useMemo(() => {
    const base = lists.symbols && lists.symbols.length > 0 ? [...lists.symbols] : ['XAUUSD', 'EURUSD', 'GBPUSD', 'BTCUSD'];
    if (symbol && !base.includes(symbol)) base.unshift(symbol);
    return base;
  }, [lists.symbols, symbol]);

  const providersList = lists.providers?.length ? lists.providers : DEFAULT_PROVIDERS;
  const gemModelsList = lists.gem_models?.length ? lists.gem_models : DEFAULT_GEM_MODELS;
  const claudeModelsList = lists.claude_models?.length ? lists.claude_models : DEFAULT_CLAUDE_MODELS;
  const tgModesList = lists.tg_modes?.length ? lists.tg_modes : DEFAULT_TG_MODES;
  const presetsList = lists.presets || [];

  const isPcOnline = Boolean(roomState && Math.floor(Date.now() / 1000) - roomState.ts < 35);

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
      {/* Top Bar Contract: 3 zones */}
      <header className="bg-white border-b border-slate-200 px-6 py-3.5">
        <div className="max-w-[1320px] mx-auto flex items-center justify-between gap-8">
          <a href="#top" className="text-lg font-bold tracking-tight text-slate-900 whitespace-nowrap shrink-0">
            SMC Remote Bridge
          </a>

          <nav className="flex items-center gap-6 overflow-x-auto text-sm font-medium text-slate-600">
            <button
              type="button"
              onClick={() => setActiveTab('control')}
              className={`py-1 whitespace-nowrap shrink-0 transition-colors border-b-2 ${
                activeTab === 'control' ? 'text-slate-900 border-slate-900' : 'border-transparent hover:text-slate-900'
              }`}
            >
              لوحة التحكم الحية
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('chart')}
              className={`py-1 whitespace-nowrap shrink-0 transition-colors border-b-2 ${
                activeTab === 'chart' ? 'text-slate-900 border-slate-900' : 'border-transparent hover:text-slate-900'
              }`}
            >
              الرسم البياني المباشر
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('files')}
              className={`py-1 whitespace-nowrap shrink-0 transition-colors border-b-2 ${
                activeTab === 'files' ? 'text-slate-900 border-slate-900' : 'border-transparent hover:text-slate-900'
              }`}
            >
              البيانات والملف
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('answer')}
              className={`py-1 whitespace-nowrap shrink-0 transition-colors border-b-2 ${
                activeTab === 'answer' ? 'text-slate-900 border-slate-900' : 'border-transparent hover:text-slate-900'
              }`}
            >
              نتيجة التحليل
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('export')}
              className={`py-1 whitespace-nowrap shrink-0 transition-colors border-b-2 ${
                activeTab === 'export' ? 'text-slate-900 border-slate-900' : 'border-transparent hover:text-slate-900'
              }`}
            >
              تصدير Python و APK
            </button>
          </nav>

          <div className="flex items-center gap-3 shrink-0">
            <button
              type="button"
              onClick={downloadPythonScript}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors whitespace-nowrap shrink-0"
            >
              <Download className="w-3.5 h-3.5" />
              <span>تحميل ملف Python</span>
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-[1320px] w-full mx-auto px-6 py-6 space-y-6">
        {(toastMsg || errorMsg) && (
          <div className="space-y-2">
            {toastMsg && (
              <div className="bg-emerald-50 border border-emerald-200 text-emerald-900 px-4 py-3 rounded-lg text-sm flex items-center justify-between">
                <span>{toastMsg}</span>
                <button type="button" onClick={() => setToastMsg('')} className="text-xs text-emerald-700 hover:underline">
                  إغلاق
                </button>
              </div>
            )}
            {errorMsg && (
              <div className="bg-rose-50 border border-rose-200 text-rose-900 px-4 py-3 rounded-lg text-sm flex items-center justify-between">
                <span className="break-words">{errorMsg}</span>
                <button type="button" onClick={() => setErrorMsg('')} className="text-xs text-rose-700 hover:underline">
                  إغلاق
                </button>
              </div>
            )}
          </div>
        )}

        {/* Direct Cloud Connection Strip (Zero Login / Zero Room Code) */}
        <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-lg font-bold text-slate-900">اتصال مباشر تلقائي مع Firebase (بدون رمز غرفة أو تسجيل دخول)</h1>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>المشروع: <span className="font-mono-num text-slate-700">{FIREBASE_META.projectId}</span></span>
                <span aria-hidden="true">·</span>
                <span>حالة السكربت: {isPcOnline ? 'اللوحة الأم متصلة ومزامنة' : 'في انتظار تشغيل smc_control_panel.py على الكمبيوتر'}</span>
                {roomState && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>الجهاز: {roomState.name}</span>
                    <span aria-hidden="true">·</span>
                    <span>{roomState.conn || (roomState.mt5 ? 'MT5 متصل' : 'MT5 غير متصل')}</span>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void handleZipDownload()}
                disabled={isExportingZip}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 transition-colors whitespace-nowrap shrink-0"
              >
                <FolderArchive className="w-3.5 h-3.5" />
                <span>{isExportingZip ? 'جاري التجهيز...' : 'تحميل مشروع APK لـ GitHub'}</span>
              </button>
            </div>
          </div>

          {roomState && (
            <div className="pt-3 border-t border-slate-100 grid grid-cols-1 md:grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-xs text-slate-500">السعر الحي (Bid / Ask)</div>
                <div className="font-mono-num font-semibold text-slate-900 mt-0.5">{roomState.price || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">الرمز النشط</div>
                <div className="font-mono-num font-semibold text-slate-900 mt-0.5">{roomState.symbol}</div>
              </div>
              <div className="md:col-span-2">
                <div className="text-xs text-slate-500">حالة التنفيذ</div>
                <div className="text-slate-800 mt-0.5 truncate">{roomState.status || 'جاهز'}</div>
              </div>
            </div>
          )}
        </section>

        {/* TAB 1: Live Control */}
        {activeTab === 'control' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-7 space-y-6">
              <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-bold text-slate-900">إعدادات المنصة والفريمات والمزوّد</h2>
                  <button
                    type="button"
                    onClick={() => void dispatchCommand('connect')}
                    className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 whitespace-nowrap shrink-0"
                  >
                    <Wifi className="w-3.5 h-3.5" />
                    <span>اتصال / إعادة اتصال MT5</span>
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">الرمز (Symbol)</label>
                    <select
                      value={symbol}
                      onChange={(e) => {
                        const v = e.target.value;
                        setSymbol(v);
                        void dispatchCommand('set', { ...currentParams(), symbol: v });
                      }}
                      className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white font-mono-num"
                    >
                      {symbolsList.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">مزوّد التحليل</label>
                    <select
                      value={provider}
                      onChange={(e) => {
                        const v = e.target.value;
                        setProvider(v);
                        void dispatchCommand('set', { ...currentParams(), provider: v });
                      }}
                      className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
                    >
                      {providersList.map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">موديل Gemini</label>
                    <select
                      value={gemModel}
                      onChange={(e) => {
                        const v = e.target.value;
                        setGemModel(v);
                        void dispatchCommand('set', { ...currentParams(), gem_model: v });
                      }}
                      className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white font-mono-num"
                    >
                      {gemModelsList.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">موديل Claude</label>
                    <select
                      value={claudeModel}
                      onChange={(e) => {
                        const v = e.target.value;
                        setClaudeModel(v);
                        void dispatchCommand('set', { ...currentParams(), claude_model: v });
                      }}
                      className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white font-mono-num"
                    >
                      {claudeModelsList.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium text-slate-600 mb-2">الفريمات الزمنية</div>
                  <div className="flex flex-wrap items-center gap-3">
                    {TF_LIST.map((tf) => (
                      <label key={tf} className="inline-flex items-center gap-1.5 text-sm font-mono-num cursor-pointer">
                        <input
                          type="checkbox"
                          checked={Boolean(tfs[tf])}
                          onChange={(e) => {
                            const next = { ...tfs, [tf]: e.target.checked };
                            setTfs(next);
                            void dispatchCommand('set', { ...currentParams(), tfs: next });
                          }}
                          className="rounded border-slate-300 text-slate-900"
                        />
                        <span>{tf}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-slate-100">
                  <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={chain}
                      onChange={(e) => {
                        setChain(e.target.checked);
                        void dispatchCommand('set', { ...currentParams(), chain: e.target.checked });
                      }}
                      className="rounded border-slate-300 text-slate-900"
                    />
                    <span>تحليل تلقائياً بعد الجلب</span>
                  </label>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-600">Telegram:</span>
                    <select
                      value={tgMode}
                      onChange={(e) => {
                        const v = e.target.value;
                        setTgMode(v);
                        void dispatchCommand('set', { ...currentParams(), tg_mode: v });
                      }}
                      className="px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg bg-white"
                    >
                      {tgModesList.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void dispatchCommand('models')}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>تحديث الموديلات</span>
                    </button>
                  </div>
                </div>
              </section>

              <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
                <h2 className="text-base font-bold text-slate-900">أزرار التحكم والتنفيذ</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => void dispatchCommand('fetch', currentParams())}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-sky-700 text-white rounded-lg hover:bg-sky-800 transition-colors"
                  >
                    <Download className="w-4 h-4" />
                    <span>جلب البيانات الحية</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('make_file', currentParams())}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-blue-700 text-white rounded-lg hover:bg-blue-800 transition-colors"
                  >
                    <FileText className="w-4 h-4" />
                    <span>إنشاء الملف فقط (.txt)</span>
                  </button>

                  <button
                    type="button"
                    disabled={workflowRunning}
                    onClick={() => void runFetchCreateDownload()}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 transition-colors sm:col-span-2 disabled:opacity-60"
                  >
                    <Zap className="w-4 h-4" />
                    <span>جلب البيانات الحية + إنشاء ملف + إرسال للتحميل</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('ai', currentParams())}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-indigo-700 text-white rounded-lg hover:bg-indigo-800 transition-colors"
                  >
                    <Play className="w-4 h-4" />
                    <span>إنشاء الملف وإرساله للمزوّد</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('fetch_ai', currentParams())}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
                  >
                    <Zap className="w-4 h-4" />
                    <span>جلب + تحليل</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('tg_answer')}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <Send className="w-4 h-4" />
                    <span>إرسال النتيجة إلى Telegram</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('tg_file')}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <Send className="w-4 h-4" />
                    <span>إنشاء ملف وإرساله لـ Telegram</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('save')}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <Save className="w-4 h-4" />
                    <span>حفظ إعدادات الكمبيوتر</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void dispatchCommand('stop')}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-rose-600 text-white rounded-lg hover:bg-rose-700 transition-colors"
                  >
                    <Square className="w-4 h-4" />
                    <span>إيقاف العملية</span>
                  </button>
                </div>
              </section>
            </div>

            <div className="lg:col-span-5 space-y-6">
              <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-bold text-slate-900">الأوامر الافتراضية</h2>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void dispatchCommand('set_prompt', { text: promptDraft })}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800"
                    >
                      <Save className="w-3.5 h-3.5" />
                      <span>حفظ الأوامر</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void dispatchCommand('reset_prompt')}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      <span>استعادة</span>
                    </button>
                  </div>
                </div>

                {presetsList.length > 0 && (
                  <div className="flex items-center gap-2">
                    <select
                      value={selectedPreset}
                      onChange={(e) => setSelectedPreset(e.target.value)}
                      className="flex-1 px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white"
                    >
                      <option value="">اختر أمراً جاهزاً لإضافته...</option>
                      {presetsList.map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => {
                        if (!selectedPreset) return;
                        setPromptDraft((cur) => (cur.trim() ? `${cur.trim()}\n${selectedPreset}` : selectedPreset));
                      }}
                      className="inline-flex items-center gap-1 px-3 py-2 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>إضافة</span>
                    </button>
                  </div>
                )}

                <textarea
                  rows={9}
                  value={promptDraft}
                  onChange={(e) => setPromptDraft(e.target.value)}
                  placeholder="تظهر الأوامر الافتراضية هنا عند الاتصال..."
                  className="w-full p-3 text-sm border border-slate-300 rounded-lg bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-900"
                />
              </section>

              <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-slate-600" />
                    <span>سجل التنفيذ المباشر</span>
                  </h2>
                </div>
                <pre className="bg-slate-950 text-slate-100 text-xs font-mono-num p-3 rounded-lg h-56 overflow-auto whitespace-pre-wrap" dir="ltr">
                  {roomState?.log || 'بانتظار السجل من اللوحة الأم...'}
                </pre>
              </section>
            </div>
          </div>
        )}

        {/* TAB 1B: Live Interactive Chart */}
        {activeTab === 'chart' && (
          <LiveCandleChart
            payload={chartPayload}
            chartActive={chartActive}
            selectedTf={chartTf}
            countdownSec={chartCountdown}
            timeframes={TF_LIST}
            onStart={() => {
              chartSyncLockUntilRef.current = Date.now() + 5000;
              setChartActive(true);
              setChartCountdown(60);
              void dispatchCommand('chart_start', { tf: chartTf });
            }}
            onStop={() => {
              chartSyncLockUntilRef.current = Date.now() + 5000;
              setChartActive(false);
              void dispatchCommand('chart_stop');
            }}
            onSelectTf={(tf) => {
              chartSyncLockUntilRef.current = Date.now() + 5000;
              setChartTf(tf);
              setChartCountdown(60);
              if (chartActive) {
                void dispatchCommand('chart_tf', { tf });
              } else {
                setChartActive(true);
                void dispatchCommand('chart_start', { tf });
              }
            }}
            onRefreshNow={() => {
              chartSyncLockUntilRef.current = Date.now() + 5000;
              setChartCountdown(60);
              if (!chartActive) setChartActive(true);
              void dispatchCommand('chart_refresh', { tf: chartTf });
            }}
          />
        )}

        {/* TAB 2: Live Data & Generated File */}
        {activeTab === 'files' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <h2 className="text-base font-bold text-slate-900">البيانات المجلوبة الحية</h2>
                  <div className="text-xs text-slate-500 font-mono-num">{dataItem.name} · v{dataItem.ver}</div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCopy(dataItem.text, 'البيانات')}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    <span>نسخ</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadTextAsset(dataItem.text, dataItem.name)}
                    disabled={!dataItem.text}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-40"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>تنزيل</span>
                  </button>
                </div>
              </div>
              <pre className="bg-slate-50 border border-slate-200 p-3 rounded-lg text-xs font-mono-num h-[520px] overflow-auto whitespace-pre-wrap">
                {dataItem.text || 'لا توجد بيانات مجلوبة بعد — اضغط "جلب البيانات الحية".'}
              </pre>
            </section>

            <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <h2 className="text-base font-bold text-slate-900">الملف المُرسل (.txt)</h2>
                  <div className="text-xs text-slate-500 font-mono-num">{fileItem.name} · v{fileItem.ver}</div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void dispatchCommand('make_file', currentParams())}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>إنشاء الآن</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadTextAsset(fileItem.text, fileItem.name)}
                    disabled={!fileItem.text}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 disabled:opacity-40"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>تحميل الملف</span>
                  </button>
                </div>
              </div>
              <pre className="bg-slate-50 border border-slate-200 p-3 rounded-lg text-xs font-mono-num h-[520px] overflow-auto whitespace-pre-wrap">
                {fileItem.text || 'لم يتم إنشاء ملف بعد — اضغط "إنشاء الملف فقط".'}
              </pre>
            </section>
          </div>
        )}

        {/* TAB 3: Analysis Result */}
        {activeTab === 'answer' && (
          <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold text-slate-900">نتيجة التحليل</h2>
                <div className="text-xs text-slate-500">{roomState?.label || 'Gemini / Claude'}</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleCopy(answerItem.text, 'نتيجة التحليل')}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>نسخ النتيجة</span>
                </button>
                <button
                  type="button"
                  onClick={() => void dispatchCommand('tg_answer')}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>إرسال إلى Telegram</span>
                </button>
              </div>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 min-h-[420px] whitespace-pre-wrap text-sm leading-7 text-slate-800">
              {answerItem.text || 'لا توجد نتيجة تحليل بعد — ابدأ التحليل من تبويب "لوحة التحكم الحية".'}
            </div>
          </section>
        )}

        {/* TAB 4: Export Studio */}
        {activeTab === 'export' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col justify-between space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                    <FileCode2 className="w-5 h-5 text-sky-700" />
                    <span>ملف الكمبيوتر (Python واحد)</span>
                  </div>
                  <p className="text-sm text-slate-600 leading-6">
                    سكربت <span className="font-mono-num">smc_control_panel.py</span> كامل في ملف واحد ({EXPORT_PREVIEWS.pythonLines} سطراً)،
                    يتصل مباشرة بـ Firebase بدون إدخال أي رمز غرفة.
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={downloadPythonScript}
                    className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
                  >
                    <Download className="w-4 h-4" />
                    <span>تحميل .py</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleCopy(EXPORT_PREVIEWS.pythonRaw, 'كود Python')}
                    className="inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm font-medium border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <Copy className="w-4 h-4" />
                    <span>نسخ</span>
                  </button>
                </div>
              </div>

              <div className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col justify-between space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                    <FolderArchive className="w-5 h-5 text-emerald-700" />
                    <span>مشروع GitHub الكامل (APK + Python)</span>
                  </div>
                  <p className="text-sm text-slate-600 leading-6">
                    حزمة جاهزة للرفع إلى GitHub تحتوي على مشروع Android APK + <span className="font-mono-num">.github/workflows/build-apk.yml</span> + ملف Python.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isExportingZip}
                  onClick={() => void handleZipDownload()}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 transition-colors disabled:opacity-60"
                >
                  <Download className="w-4 h-4" />
                  <span>{isExportingZip ? 'جاري التجهيز...' : 'تحميل SMC-Phone-GitHub-APK.zip'}</span>
                </button>
              </div>

              <div className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col justify-between space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-slate-900 font-bold text-base">
                    <FileCode2 className="w-5 h-5 text-indigo-700" />
                    <span>كود الهاتف في ملف واحد</span>
                  </div>
                  <p className="text-sm text-slate-600 leading-6">
                    ملف <span className="font-mono-num">MainActivity.kt</span> ({EXPORT_PREVIEWS.kotlinLines} سطراً) يتصل تلقائياً عبر الشبكة المحلية أو Firebase بدون أي رمز أو تسجيل دخول.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={downloadMainActivityKt}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  <span>تحميل MainActivity.kt</span>
                </button>
              </div>
            </div>

            <section className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
              <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <Cloud className="w-5 h-5 text-slate-700" />
                <span>الربط السحابي المباشر (مفعل افتراضياً بدون تسجيل دخول)</span>
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm text-slate-700 leading-7">
                <ol className="list-decimal list-inside space-y-2">
                  <li>حمّل <span className="font-mono-num font-semibold">smc_control_panel.py</span> وشغّله على الكمبيوتر: <code className="font-mono-num bg-slate-100 px-1.5 py-0.5 rounded">python smc_control_panel.py</code> — سيتصل مباشرة بـ Firebase.</li>
                  <li>حمّل <span className="font-mono-num font-semibold">SMC-Phone-GitHub-APK.zip</span> وفك ضغطه ثم ارفع المحتويات إلى GitHub (يحتوي على مسار Actions لبناء الـ APK + ملف Python).</li>
                  <li>افتح تبويب <strong>Actions</strong> في GitHub وحمّل <span className="font-mono-num">app-debug.apk</span> بعد انتهاء البناء.</li>
                  <li>افتح التطبيق على هاتفك: سيتعرف تلقائياً على الشبكة المحلية أو يتصل مباشرة بـ Firebase فوراً بدون كتابة أي رمز.</li>
                </ol>

                <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-2 text-xs font-mono-num" dir="ltr">
                  <div className="font-semibold text-slate-900 flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    <span>Zero-Config Direct Cloud Sync</span>
                  </div>
                  <div>Project ID: {FIREBASE_META.projectId}</div>
                  <div>Database ID: {FIREBASE_META.databaseId}</div>
                  <div>Auto Channel: {DEFAULT_PAIR_CODE}</div>
                  <div>Local Bridge: HTTP :8765 + UDP :8766</div>
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
