import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import {
  getFirestore,
  doc,
  getDocFromServer,
  setDoc,
  onSnapshot,
  type Unsubscribe,
} from 'firebase/firestore';
import firebaseConfig from '../firebase-applet-config.json';

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app, firebaseConfig.firestoreDatabaseId);
export const auth = getAuth(app);

export const DEFAULT_PAIR_CODE = 'SMC-AUTO-BRIDGE';

export const FIREBASE_META = {
  projectId: firebaseConfig.projectId,
  databaseId: firebaseConfig.firestoreDatabaseId,
  apiKey: firebaseConfig.apiKey,
};

export enum OperationType {
  CREATE = 'create',
  UPDATE = 'update',
  DELETE = 'delete',
  LIST = 'list',
  GET = 'get',
  WRITE = 'write',
}

export interface FirestoreErrorInfo {
  error: string;
  operationType: OperationType;
  path: string | null;
  authInfo: {
    userId?: string | null;
    email?: string | null;
    emailVerified?: boolean | null;
    isAnonymous?: boolean | null;
    tenantId?: string | null;
    providerInfo?: {
      providerId?: string | null;
      email?: string | null;
    }[];
  };
}

export function handleFirestoreError(
  error: unknown,
  operationType: OperationType,
  path: string | null
): never {
  const errInfo: FirestoreErrorInfo = {
    error: error instanceof Error ? error.message : String(error),
    authInfo: {
      userId: auth.currentUser?.uid,
      email: auth.currentUser?.email,
      emailVerified: auth.currentUser?.emailVerified,
      isAnonymous: auth.currentUser?.isAnonymous,
      tenantId: auth.currentUser?.tenantId,
      providerInfo:
        auth.currentUser?.providerData?.map((provider) => ({
          providerId: provider.providerId,
          email: provider.email,
        })) || [],
    },
    operationType,
    path,
  };
  console.error('Firestore Error: ', JSON.stringify(errInfo));
  throw new Error(JSON.stringify(errInfo));
}

export async function testConnection(): Promise<boolean> {
  try {
    await getDocFromServer(doc(db, 'rooms', pairCodeToRoomId(DEFAULT_PAIR_CODE)));
    return true;
  } catch (error) {
    if (error instanceof Error && error.message.includes('the client is offline')) {
      console.error('Please check your Firebase configuration.');
      return false;
    }
    return true;
  }
}

void testConnection();

export function normalizePairCode(code: string): string {
  return code.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
}

export function pairCodeToRoomId(code: string): string {
  return normalizePairCode(code).toLowerCase();
}

export interface RoomState {
  ok: number;
  name: string;
  mt5: boolean;
  conn: string;
  busy: boolean;
  ai: boolean;
  status: string;
  price: string;
  symbol: string;
  tfs: Record<string, boolean>;
  chain: boolean;
  provider: string;
  gem_model: string;
  claude_model: string;
  tg_mode: string;
  label: string;
  vers: Record<string, number>;
  log: string;
  ts: number;
}

function safeParseJson<T>(raw: unknown, fallback: T): T {
  if (typeof raw !== 'string' || !raw.trim()) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function subscribeRoomState(
  roomId: string,
  onData: (state: RoomState | null) => void,
  onErr: (msg: string) => void
): Unsubscribe {
  const path = `rooms/${roomId}`;
  return onSnapshot(
    doc(db, 'rooms', roomId),
    (snap) => {
      if (!snap.exists()) {
        onData(null);
        return;
      }
      const d = snap.data();
      onData({
        ok: Number(d.ok ?? 1),
        name: String(d.name ?? 'PC'),
        mt5: Boolean(d.mt5),
        conn: String(d.conn ?? ''),
        busy: Boolean(d.busy),
        ai: Boolean(d.ai),
        status: String(d.status ?? ''),
        price: String(d.price ?? ''),
        symbol: String(d.symbol ?? 'XAUUSD'),
        tfs: safeParseJson<Record<string, boolean>>(d.tfsJson, {}),
        chain: Boolean(d.chain),
        provider: String(d.provider ?? 'Gemini'),
        gem_model: String(d.gem_model ?? 'gemini-flash-latest'),
        claude_model: String(d.claude_model ?? 'claude-sonnet-5-5'),
        tg_mode: String(d.tg_mode ?? 'يدوي'),
        label: String(d.label ?? ''),
        vers: safeParseJson<Record<string, number>>(d.versJson, {}),
        log: String(d.log ?? ''),
        ts: Number(d.ts ?? 0),
      });
    },
    (error) => {
      try {
        handleFirestoreError(error, OperationType.GET, path);
      } catch (e) {
        onErr(e instanceof Error ? e.message : String(e));
      }
    }
  );
}

export function subscribeRoomItem(
  roomId: string,
  itemId: 'data' | 'file' | 'answer' | 'prompt' | 'lists' | 'resp',
  onData: (item: Record<string, unknown> | null) => void,
  onErr: (msg: string) => void
): Unsubscribe {
  const path = `rooms/${roomId}/items/${itemId}`;
  return onSnapshot(
    doc(db, 'rooms', roomId, 'items', itemId),
    (snap) => {
      onData(snap.exists() ? (snap.data() as Record<string, unknown>) : null);
    },
    (error) => {
      try {
        handleFirestoreError(error, OperationType.GET, path);
      } catch (e) {
        onErr(e instanceof Error ? e.message : String(e));
      }
    }
  );
}

export async function sendRoomCommand(
  roomId: string,
  action: string,
  params: Record<string, unknown> = {}
): Promise<string> {
  const cmdId = `cmd_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const path = `rooms/${roomId}/items/cmd`;
  try {
    await setDoc(doc(db, 'rooms', roomId, 'items', 'cmd'), {
      kind: 'cmd',
      id: cmdId,
      action,
      paramsJson: JSON.stringify(params).slice(0, 30000),
      ts: Math.floor(Date.now() / 1000),
    });
    return cmdId;
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}
