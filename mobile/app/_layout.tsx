import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { SettingsProvider } from '@/store/settings';
import { theme } from '@/theme';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <SettingsProvider>
        <StatusBar style="light" />
        {/* 화면마다 자체 헤더를 그리므로(목업 구조) 네비게이션 헤더는 숨긴다 */}
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: theme.bg },
            animation: 'fade',
          }}
        />
      </SettingsProvider>
    </SafeAreaProvider>
  );
}
