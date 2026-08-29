import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { SettingsProvider } from '@/store/settings';
import { useTheme } from '@/theme';

export default function RootLayout() {
  const t = useTheme();
  return (
    <SafeAreaProvider>
      <SettingsProvider>
        <StatusBar style="auto" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: t.surface },
            headerTintColor: t.textPrimary,
            headerTitleStyle: { fontWeight: '700' },
            contentStyle: { backgroundColor: t.bg },
          }}>
          <Stack.Screen name="index" options={{ title: '시작하기' }} />
          <Stack.Screen name="user/home" options={{ title: '내 수면 리포트' }} />
          <Stack.Screen name="user/session/[id]" options={{ title: '세션 상세' }} />
          <Stack.Screen name="admin/index" options={{ title: '관리자' }} />
          <Stack.Screen name="admin/[userId]" options={{ title: '사용자 데이터' }} />
        </Stack>
      </SettingsProvider>
    </SafeAreaProvider>
  );
}
