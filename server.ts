import express from 'express';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { GoogleGenAI } from '@google/genai';
import 'dotenv/config';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 3000);
const isProduction = process.env.NODE_ENV === 'production';

interface FirebaseAppletConfig {
  projectId: string;
  firestoreDatabaseId: string;
  apiKey: string;
}

function loadFirebaseConfig(): FirebaseAppletConfig | null {
  try {
    const cfgPath = path.resolve(__dirname, 'firebase-applet-config.json');
    if (!fs.existsSync(cfgPath)) return null;
    const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf-8')) as Partial<FirebaseAppletConfig>;
    if (raw.projectId && raw.firestoreDatabaseId && raw.apiKey) {
      return {
        projectId: raw.projectId,
        firestoreDatabaseId: raw.firestoreDatabaseId,
        apiKey: raw.apiKey,
      };
    }
    return null;
  } catch {
    return null;
  }
}

const fbConfig = loadFirebaseConfig();

function getGeminiClient(): GoogleGenAI {
  const apiKey = (process.env.GEMINI_API_KEY || '').trim();
  if (!apiKey || apiKey === 'MY_GEMINI_API_KEY') {
    throw new Error('لم يتم العثور على GEMINI_API_KEY في إعدادات الخادم (Settings > Secrets).');
  }
  return new GoogleGenAI({
    apiKey,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      },
    },
  });
}

function crc32Ver(text: string): number {
  let crc = 0xffffffff;
  const buf = Buffer.from(text, 'utf-8');
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return ((crc ^ 0xffffffff) >>> 0) & 0x7fffffff || 1;
}

async function pushAnswerToFirestore(roomId: string, answerText: string): Promise<void> {
  if (!fbConfig) return;
  if (!/^[a-zA-Z0-9_-]{12,64}$/.test(roomId)) return;
  const ver = crc32Ver(answerText);
  const ts = Math.floor(Date.now() / 1000);
  const url = `https://firestore.googleapis.com/v1/projects/${encodeURIComponent(
    fbConfig.projectId
  )}/databases/${encodeURIComponent(fbConfig.firestoreDatabaseId)}/documents/rooms/${encodeURIComponent(
    roomId
  )}/items/answer?key=${encodeURIComponent(fbConfig.apiKey)}`;

  const payload = {
    fields: {
      kind: { stringValue: 'answer' },
      name: { stringValue: 'SMC_gemini_answer.txt' },
      text: { stringValue: answerText.slice(0, 700000) },
      ver: { integerValue: String(ver) },
      ts: { integerValue: String(ts) },
    },
  };

  const resp = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const errTxt = await resp.text().catch(() => '');
    throw new Error(`Firestore sync HTTP ${resp.status}: ${errTxt.slice(0, 140)}`);
  }
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: '1mb' }));

  app.get('/api/health', (_req, res) => {
    const hasKey = Boolean((process.env.GEMINI_API_KEY || '').trim() && process.env.GEMINI_API_KEY !== 'MY_GEMINI_API_KEY');
    res.json({ ok: true, geminiReady: hasKey, model: 'gemini-4-hydrogen' });
  });

  app.post('/api/gemini/analyze', async (req, res) => {
    try {
      const body = req.body as {
        content?: unknown;
        symbol?: unknown;
        prompt?: unknown;
        roomId?: unknown;
        pushToFirebase?: unknown;
      };
      const rawContent = typeof body?.content === 'string' ? body.content.trim() : '';
      if (!rawContent) {
        res.status(400).json({ ok: false, error: 'محتوى الملف فارغ — أنشئ الملف أو اجلب البيانات أولاً.' });
        return;
      }

      const symbol = typeof body?.symbol === 'string' && body.symbol.trim() ? body.symbol.trim().slice(0, 40) : 'XAUUSD';
      const extraPrompt = typeof body?.prompt === 'string' && body.prompt.trim() ? body.prompt.trim().slice(0, 8000) : '';
      const roomId = typeof body?.roomId === 'string' ? body.roomId.trim().toLowerCase() : '';
      const pushToFirebase = Boolean(body?.pushToFirebase);

      const clippedContent = rawContent.slice(0, 500000);
      const userPrompt = extraPrompt
        ? `تعليمات إضافية:\n${extraPrompt}\n\nمحتوى الملف (${symbol}):\n${clippedContent}`
        : `اقرأ ملف بيانات SMC المرفق لـ ${symbol} واتبع التعليمات بدقة، واكتب التحليل والصفقة كاملة باللغة العربية:\n\n${clippedContent}`;

      const ai = getGeminiClient();
      const response = await ai.models.generateContent({
        model: 'gemini-4-hydrogen',
        contents: userPrompt,
        config: {
          systemInstruction:
            'أنت محلل فني محترف في أسواق المال وتقنيات SMC وتدفق الأوامر (Order Flow). اقرأ الملف بدقة واستخرج: الاتجاه العام، نقطة الدخول، وقف الخسارة، الأهداف الثلاثة، نسبة العائد للمخاطرة، ودرجة الثقة من 100، أو صرّح بعدم وجود فرصة واضحة. اكتب الإجابة بالعربية الواضحة والمنظمة.',
        },
      });

      const answer = (response.text || '').trim();
      if (!answer) {
        res.status(502).json({ ok: false, error: 'أعاد Gemini رداً فارغاً.' });
        return;
      }

      let syncedToFirebase = false;
      if (pushToFirebase && roomId) {
        try {
          await pushAnswerToFirestore(roomId, answer);
          syncedToFirebase = true;
        } catch (fbErr) {
          console.error('Firestore push warning:', fbErr);
        }
      }

      res.json({
        ok: true,
        answer,
        model: 'gemini-4-hydrogen',
        label: 'Gemini الداخلي (gemini-4-hydrogen)',
        syncedToFirebase,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const status = msg.includes('GEMINI_API_KEY') ? 503 : 500;
      res.status(status).json({ ok: false, error: msg });
    }
  });

  if (!isProduction) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        hmr: process.env.DISABLE_HMR !== 'true',
      },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distDir = path.resolve(__dirname, 'dist');
    app.use(express.static(distDir));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distDir, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`SMC Bridge & Internal Gemini Server running on http://0.0.0.0:${PORT}`);
  });
}

void startServer();
