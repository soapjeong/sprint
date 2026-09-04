import { Jua_400Regular, useFonts } from '@expo-google-fonts/jua';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { SettingsProvider } from '@/store/settings';
import { theme } from '@/theme';

export default function RootLayout() {
  // 앱 전체가 둥근 주아체 하나로 그려지므로, 글꼴을 받기 전에는 빈 밤하늘만 보여준다
  // (기본 글꼴로 한 번 그렸다가 바뀌면 글자가 튀어 보인다).
  const [fontsLoaded] = useFonts({ Jua_400Regular });

  return (
    <SafeAreaProvider>
      <SettingsProvider>
        <StatusBar style="light" />
        {fontsLoaded ? (
          // 화면마다 자체 헤더를 그리므로(목업 구조) 네비게이션 헤더는 숨긴다
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: theme.bg },
              animation: 'fade',
            }}
          />
        ) : (
          <View style={{ flex: 1, backgroundColor: theme.bg }} />
        )}
      </SettingsProvider>
    </SafeAreaProvider>
  );
}
