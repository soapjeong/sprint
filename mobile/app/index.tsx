import { useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native';
import { api, ApiError } from '@/api/client';
import type { PendingDevice } from '@/api/types';
import { useSettings } from '@/store/settings';
import { spacing, useTheme } from '@/theme';
import { Body, Button, Caption, Card, ErrorNote, Field, Heading, Loading, Row, Screen, Title } from '@/ui/kit';
import { formatDateTime } from '@/util/format';

const ID_RE = /^[A-Za-z0-9_.-]{2,32}$/;

/**
 * 첫 화면 — 사용자 ID 등록/로그인 + 기기 등록.
 * 등록이 끝나면 사용자 페이지로 넘어가고, 다음 실행부터는 저장된 ID로 바로 들어간다.
 */
export default function OnboardingScreen() {
  const router = useRouter();
  const t = useTheme();
  const { settings, ready, update } = useSettings();

  const [serverUrl, setServerUrl] = useState(settings.serverUrl);
  const [userId, setUserId] = useState('');
  const [name, setName] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [deviceLabel, setDeviceLabel] = useState('');
  const [busy, setBusy] = useState<null | 'user' | 'device' | 'scan'>(null);
  const [found, setFound] = useState<PendingDevice[] | null>(null);
  const [manual, setManual] = useState(false);
  const [error, setError] = useState('');
  const [step, setStep] = useState<'user' | 'device'>('user');

  useEffect(() => {
    if (!ready) return;
    setServerUrl(settings.serverUrl);
    if (settings.userId) {
      setUserId(settings.userId);
      setStep('device');
    }
    if (settings.userId && settings.deviceId) {
      router.replace('/user/home');
    }
  }, [ready, settings.userId, settings.deviceId, settings.serverUrl, router]);

  if (!ready) {
    return (
      <Screen>
        <Loading label="설정을 불러오는 중…" />
      </Screen>
    );
  }

  async function submitUser(mode: 'create' | 'login') {
    setError('');
    if (!ID_RE.test(userId.trim())) {
      setError('ID는 영문/숫자와 . _ - 만 사용해 2~32자로 입력하세요.');
      return;
    }
    setBusy('user');
    try {
      const id = userId.trim();
      if (mode === 'create') {
        await api.createUser(serverUrl, id, name.trim());
      } else {
        await api.getUser(serverUrl, id);
      }
      await update({ serverUrl: serverUrl.trim(), userId: id });
      setStep('device');
    } catch (e) {
      const err = e as ApiError;
      setError(
        err.status === 409
          ? '이미 등록된 ID 입니다. "기존 ID로 계속"을 눌러주세요.'
          : err.status === 404
            ? '등록되지 않은 ID 입니다. "새 ID 등록"을 눌러주세요.'
            : err.message,
      );
    } finally {
      setBusy(null);
    }
  }

  /** 기기 ID 는 칩 MAC 에서 만들어지므로 손으로 적지 않고 목록에서 고른다. */
  async function scanDevices() {
    setError('');
    setBusy('scan');
    try {
      const list = await api.pendingDevices(serverUrl);
      setFound(list);
      if (list.length === 1) setDeviceId(list[0].device_id);
      if (list.length === 0) {
        setError('연결된 기기를 찾지 못했습니다. 기기에 USB를 연결하고 브리지를 실행한 뒤 다시 눌러주세요.');
      }
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function submitDevice() {
    setError('');
    if (!ID_RE.test(deviceId.trim())) {
      setError('기기를 먼저 목록에서 선택하거나 ID를 직접 입력하세요.');
      return;
    }
    setBusy('device');
    try {
      await api.registerDevice(serverUrl, deviceId.trim(), userId.trim(), deviceLabel.trim());
      await update({ deviceId: deviceId.trim() });
      router.replace('/user/home');
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}>
          <View style={{ gap: spacing.xs }}>
            <Title>DormX 수면 케어</Title>
            <Body muted>사용자 ID와 기기를 등록하면 세션 기록이 ID별로 저장됩니다.</Body>
          </View>

          {error ? <ErrorNote message={error} /> : null}

          <Card>
            <Heading>1. 서버 주소</Heading>
            <Field
              label="서버 주소"
              value={serverUrl}
              onChangeText={setServerUrl}
              placeholder="http://192.168.0.10:8000"
              keyboardType="url"
              hint="기기 로그를 올리는 백엔드 주소입니다. 같은 Wi-Fi의 PC 주소를 넣으세요."
            />
          </Card>

          <Card>
            <Heading>2. 사용자 ID</Heading>
            <Field
              label="사용자 ID"
              value={userId}
              onChangeText={setUserId}
              placeholder="sub01"
              editable={step === 'user'}
            />
            {step === 'user' ? (
              <>
                <Field label="이름(선택)" value={name} onChangeText={setName} placeholder="조민서" />
                <Row>
                  <View style={{ flex: 1 }}>
                    <Button label="새 ID 등록" onPress={() => submitUser('create')} loading={busy === 'user'} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Button
                      label="기존 ID로 계속"
                      variant="secondary"
                      onPress={() => submitUser('login')}
                      loading={busy === 'user'}
                    />
                  </View>
                </Row>
              </>
            ) : (
              <Row style={{ alignItems: 'center' }}>
                <Caption>확인됨 · 이 ID로 데이터가 쌓입니다.</Caption>
                <View style={{ flex: 1 }} />
                <Button label="ID 변경" variant="secondary" onPress={() => setStep('user')} />
              </Row>
            )}
          </Card>

          <Card>
            <Heading>3. 기기 등록</Heading>
            <Body muted>
              기기 ID는 칩에 새겨진 고유 번호(MAC)라 직접 입력할 필요가 없습니다. 기기를 켜 두고 아래에서
              찾아 선택하세요.
            </Body>
            <Button
              label={busy === 'scan' ? '찾는 중…' : '연결된 기기 찾기'}
              onPress={scanDevices}
              loading={busy === 'scan'}
              disabled={step !== 'device'}
            />

            {found?.map((d) => {
              const selected = deviceId === d.device_id;
              return (
                <Pressable
                  key={d.device_id}
                  onPress={() => setDeviceId(d.device_id)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  style={({ pressed }) => ({
                    borderWidth: 1,
                    borderColor: selected ? t.accent : t.border,
                    backgroundColor: selected ? t.surfaceAlt : 'transparent',
                    borderRadius: 10,
                    padding: spacing.md,
                    gap: 2,
                    opacity: pressed ? 0.7 : 1,
                  })}>
                  <Body>{d.device_id}</Body>
                  <Caption>{`마지막 신호 ${formatDateTime(d.last_seen_at)}`}</Caption>
                </Pressable>
              );
            })}

            {manual ? (
              <Field
                label="기기 ID 직접 입력"
                value={deviceId}
                onChangeText={setDeviceId}
                placeholder="DORMX-246F28AABBCC"
                hint="기기 시리얼 로그의 '@ID,...' 줄에 찍히는 값입니다."
                editable={step === 'device'}
              />
            ) : (
              <Pressable onPress={() => setManual(true)} hitSlop={8}>
                <Caption>기기를 못 찾겠다면 · ID 직접 입력하기</Caption>
              </Pressable>
            )}

            <Field
              label="기기 별칭(선택)"
              value={deviceLabel}
              onChangeText={setDeviceLabel}
              placeholder="내 침대"
              editable={step === 'device'}
            />
            <Button
              label="기기 등록하고 시작"
              onPress={submitDevice}
              loading={busy === 'device'}
              disabled={step !== 'device' || !deviceId}
            />
            {step !== 'device' ? <Caption>사용자 ID를 먼저 확인해 주세요.</Caption> : null}
          </Card>

          <Button label="관리자 페이지" variant="secondary" onPress={() => router.push('/admin')} />
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
