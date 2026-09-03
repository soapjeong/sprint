import { useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import { useSettings } from '@/store/settings';
import { radius, spacing, theme } from '@/theme';
import { Body, Button, Caption, Card, ErrorNote, Field, Loading, MoonIcon, Screen, Title } from '@/ui/kit';

const NICK_RE = /^[A-Za-z0-9가-힣_.-]{2,16}$/;

/**
 * 시작 화면 — 닉네임과 비밀번호만 받는다.
 * 기기 연결은 홈 화면의 상태 칩에서 처리하므로 여기서 묻지 않는다.
 */
export default function StartScreen() {
  const router = useRouter();
  const { settings, ready, update } = useSettings();

  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [nickname, setNickname] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // 배포 빌드에는 서버 주소가 이미 들어 있다(app.json 의 extra.defaultServerUrl).
  // 개발·현장 점검용으로 로고를 길게 누르면 주소를 바꿀 수 있게 열어둔다.
  const [serverOpen, setServerOpen] = useState(false);
  const [serverUrl, setServerUrl] = useState(settings.serverUrl);

  useEffect(() => {
    setServerUrl(settings.serverUrl);
  }, [settings.serverUrl]);

  useEffect(() => {
    if (ready && settings.userId && settings.userToken) router.replace('/user/home');
  }, [ready, settings.userId, settings.userToken, router]);

  if (!ready) {
    return (
      <Screen>
        <Loading label="준비 중…" />
      </Screen>
    );
  }

  async function submit() {
    setError('');
    const nick = nickname.trim();
    if (!NICK_RE.test(nick)) {
      setError('닉네임은 한글·영문·숫자로 2~16자로 지어주세요.');
      return;
    }
    if (password.length < 8) {
      setError('비밀번호는 8자 이상이어야 해요.');
      return;
    }
    setBusy(true);
    try {
      const base = serverUrl.trim() || settings.serverUrl;
      const auth =
        mode === 'signup'
          ? await api.signUp(base, nick, nick, password)
          : await api.logIn(base, nick, password);
      await update({ serverUrl: base, userId: nick, userToken: auth.access_token });
      router.replace('/user/home');
    } catch (e) {
      const err = e as ApiError;
      setError(
        err.status === 409
          ? '이미 있는 닉네임이에요. 로그인으로 들어와 주세요.'
          : err.status === 401
            ? '닉네임이나 비밀번호가 맞지 않아요.'
            : err.message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView
          contentContainerStyle={{ padding: spacing.xl, gap: spacing.xl, flexGrow: 1, justifyContent: 'center' }}
          keyboardShouldPersistTaps="handled">
          <Pressable
            onLongPress={() => setServerOpen((v) => !v)}
            delayLongPress={700}
            style={{ alignItems: 'center', gap: spacing.md }}>
            <MoonIcon size={76} />
            <Title>DormX</Title>
            <Caption>잠들기 좋은 온도를 찾아드려요</Caption>
          </Pressable>

          {error ? <ErrorNote message={error} /> : null}

          <Card>
            {/* 로그인 / 회원가입 전환 */}
            <View
              style={{
                flexDirection: 'row',
                backgroundColor: theme.surfaceAlt,
                borderRadius: radius.pill,
                padding: 4,
              }}>
              {(['login', 'signup'] as const).map((m) => (
                <Pressable
                  key={m}
                  onPress={() => {
                    setMode(m);
                    setError('');
                  }}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: mode === m }}
                  style={{
                    flex: 1,
                    paddingVertical: 11,
                    borderRadius: radius.pill,
                    alignItems: 'center',
                    backgroundColor: mode === m ? theme.moon : 'transparent',
                  }}>
                  <Text
                    style={{
                      color: mode === m ? theme.onAccent : theme.textSecondary,
                      fontWeight: '700',
                      fontSize: 15,
                    }}>
                    {m === 'login' ? '로그인' : '회원가입'}
                  </Text>
                </Pressable>
              ))}
            </View>

            {serverOpen ? (
              <Field
                label="서버 주소 (개발용)"
                value={serverUrl}
                onChangeText={setServerUrl}
                onBlur={() => update({ serverUrl: serverUrl.trim() })}
                placeholder="http://192.168.0.10:8000"
                keyboardType="url"
                hint="로고를 길게 누르면 열리고 닫혀요."
              />
            ) : null}

            <Field
              label="닉네임"
              value={nickname}
              onChangeText={setNickname}
              placeholder="예: 민서"
              maxLength={16}
            />
            <Field
              label="비밀번호"
              value={password}
              onChangeText={setPassword}
              placeholder="8자 이상"
              secureTextEntry
              onSubmitEditing={submit}
              returnKeyType="done"
            />
            <Button label={mode === 'signup' ? '시작하기' : '들어가기'} onPress={submit} loading={busy} />
            <Caption>
              {mode === 'signup'
                ? '닉네임으로 내 기록이 저장돼요. 비밀번호는 나만 볼 수 있게 지켜줘요.'
                : '처음이라면 위에서 회원가입을 눌러주세요.'}
            </Caption>
          </Card>

          <View style={{ alignItems: 'center' }}>
            <Body muted>좋은 밤 되세요 🌙</Body>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
