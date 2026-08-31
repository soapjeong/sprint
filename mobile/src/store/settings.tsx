import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const KEY = 'dormx.settings.v1';

export type Settings = {
  serverUrl: string;
  userId: string | null;
  /** 로그인 후 서버가 준 접근 토큰 */
  userToken: string | null;
  deviceId: string | null;
};

const defaultServerUrl =
  (Constants.expoConfig?.extra as { defaultServerUrl?: string } | undefined)?.defaultServerUrl ??
  'http://localhost:8000';

const initial: Settings = {
  serverUrl: defaultServerUrl,
  userId: null,
  userToken: null,
  deviceId: null,
};

type Ctx = {
  settings: Settings;
  ready: boolean;
  update: (patch: Partial<Settings>) => Promise<void>;
  signOut: () => Promise<void>;
};

const SettingsContext = createContext<Ctx | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(initial);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        if (raw) setSettings({ ...initial, ...(JSON.parse(raw) as Partial<Settings>) });
      } catch {
        // 저장소를 읽지 못해도 기본값으로 계속 진행한다
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const persist = useCallback(async (next: Settings) => {
    setSettings(next);
    try {
      await AsyncStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // 저장 실패는 앱 동작을 막지 않는다(메모리 상태는 유지)
    }
  }, []);

  const update = useCallback(
    async (patch: Partial<Settings>) => {
      await persist({ ...settings, ...patch });
    },
    [persist, settings],
  );

  const signOut = useCallback(async () => {
    await persist({ ...initial, serverUrl: settings.serverUrl });
  }, [persist, settings.serverUrl]);

  const value = useMemo<Ctx>(() => ({ settings, ready, update, signOut }), [settings, ready, update, signOut]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): Ctx {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('SettingsProvider 안에서만 사용할 수 있습니다.');
  return ctx;
}
