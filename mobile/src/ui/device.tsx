import React from 'react';
import { Modal, Pressable, View } from 'react-native';
import { Text } from '@/ui/typography';
import type { DeviceStatus, PendingDevice } from '@/api/types';
import { radius, spacing, theme } from '@/theme';
import { Body, Button, Caption, Heading, Loading } from './kit';
import { formatDateTime } from '@/util/format';

export type LinkView = { color: string; label: string; hint: string };

/**
 * 기기 연결 상태를 색과 문구로 알려준다.
 * "케이블이 빠졌다"와 "기기가 응답하지 않는다(전원·배터리)"를 구분하는 게 핵심.
 */
export function describeLink(status: DeviceStatus | null, hasDevice: boolean): LinkView {
  if (!hasDevice) {
    return { color: theme.coral, label: '기기 미등록', hint: '눌러서 기기를 연결해 주세요' };
  }
  if (!status) {
    return { color: theme.textMuted, label: '확인 중', hint: '기기 상태를 확인하고 있어요' };
  }
  if (status.online) {
    return { color: theme.mint, label: '기기 연결됨', hint: '바로 시작할 수 있어요' };
  }
  if (status.device.link_state === 'no_data') {
    return {
      color: theme.amber,
      label: '기기 응답 없음',
      hint: '기기 전원이 꺼졌거나 배터리가 부족해요',
    };
  }
  return {
    color: theme.coral,
    label: '기기 연결 안 됨',
    hint: 'USB 케이블과 브리지 실행을 확인해 주세요',
  };
}

/** start 버튼 옆에 붙는 상태 칩 */
export function LinkChip({ view, onPress }: { view: LinkView; onPress?: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'text'}
      accessibilityLabel={`${view.label}. ${view.hint}`}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        alignSelf: 'center',
        backgroundColor: theme.surfaceAlt,
        borderRadius: radius.pill,
        paddingVertical: 9,
        paddingHorizontal: spacing.lg,
        opacity: pressed ? 0.75 : 1,
      })}>
      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: view.color }} />
      <Text style={{ color: theme.textPrimary, fontSize: 13, fontWeight: '700' }}>{view.label}</Text>
      <Text style={{ color: theme.textMuted, fontSize: 12 }}>· {view.hint}</Text>
    </Pressable>
  );
}

/** 기기 연결(등록) 시트 — 칩을 누르면 뜬다 */
export function DeviceLinkSheet({
  visible,
  devices,
  loading,
  error,
  onPick,
  onRefresh,
  onClose,
}: {
  visible: boolean;
  devices: PendingDevice[] | null;
  loading: boolean;
  error: string;
  onPick: (deviceId: string) => void;
  onRefresh: () => void;
  onClose: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: 'rgba(4,7,26,0.72)', justifyContent: 'flex-end' }}>
        <View
          style={{
            backgroundColor: theme.surface,
            borderTopLeftRadius: radius.sheet,
            borderTopRightRadius: radius.sheet,
            padding: spacing.xl,
            paddingBottom: spacing.xxl,
            gap: spacing.lg,
          }}>
          <View style={{ alignItems: 'center', gap: 6 }}>
            <View style={{ width: 44, height: 5, borderRadius: 3, backgroundColor: theme.surfaceSoft }} />
            <Heading>기기 연결</Heading>
            <Caption>기기를 켜 두면 아래에 나타나요</Caption>
          </View>

          {error ? <Caption color={theme.coral}>{error}</Caption> : null}
          {loading ? <Loading label="기기를 찾는 중…" /> : null}

          {!loading && devices?.length === 0 ? (
            <Body muted>연결된 기기를 찾지 못했어요. 기기를 켜고 다시 찾아주세요.</Body>
          ) : null}

          {devices?.map((d) => (
            <Pressable
              key={d.device_id}
              onPress={() => onPick(d.device_id)}
              style={({ pressed }) => ({
                backgroundColor: theme.surfaceAlt,
                borderRadius: radius.tile,
                padding: spacing.lg,
                gap: 2,
                opacity: pressed ? 0.75 : 1,
              })}>
              <Body>{d.device_id}</Body>
              <Caption>마지막 신호 {formatDateTime(d.last_seen_at)}</Caption>
            </Pressable>
          ))}

          <Button label="다시 찾기" variant="soft" onPress={onRefresh} loading={loading} />
          <Button label="닫기" variant="ghost" onPress={onClose} />
        </View>
      </View>
    </Modal>
  );
}
