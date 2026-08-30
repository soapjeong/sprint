# DormX Sleep 모바일 앱 (Expo / React Native)

사용자 페이지와 관리자 페이지를 한 앱에서 운영한다.

## 개발 중 실행 (Expo Go)

```bash
cd mobile
npm install
npx expo start          # Expo Go 앱으로 QR 스캔
npx expo start --tunnel # 같은 Wi-Fi 인데도 연결이 안 될 때
```

Expo Go 는 "데모 전용"이 아니라 **개발 중 미리보기 도구**다. 아래 EAS 빌드로 만든 결과물이
스토어에 올리는 실제 앱이며, 코드는 그대로 쓴다.

## 배포용 앱 빌드 (EAS)

```bash
npm install -g eas-cli
eas login                       # Expo 계정 필요(무료)
eas build:configure

npm run build:android:preview   # 설치용 APK — 폰에 바로 설치해 테스트
npm run build:android           # Play 스토어용 AAB
npm run build:ios               # App Store 용 (Apple 개발자 계정 필요)
```

빌드 프로파일은 `eas.json`, 앱 식별자(`com.dormx.sleep`)와 버전은 `app.json` 에 있다.
`expo-build-properties` 로 안드로이드 `usesCleartextTraffic` 을 켜 두어 배포 빌드에서도
`http://` 로컬 서버에 붙는다. 서버를 HTTPS 로 올리면 이 설정은 지우는 편이 안전하다.

첫 화면에서 서버 주소를 PC의 LAN IP(`http://192.168.0.x:8000`)로 입력한다.
`app.json` 의 `extra.defaultServerUrl` 을 바꾸면 기본값이 바뀐다.

## 화면 구성

```
app/
  index.tsx              첫 화면 — 서버 주소 → 사용자 ID 등록/로그인 → 기기 등록
  user/home.tsx          사용자 페이지 — 아침 수면 평가 카드, 요약 지표, SOL 추이, 온도별 성적
  user/session/[id].tsx  세션 상세 — 결과, 측정 요약, 기기 이벤트 타임라인
  admin/index.tsx        관리자 페이지 — 토큰 인증 후 ID별 데이터 현황
  admin/[userId].tsx     관리자 — 특정 ID의 기기·세션·이벤트 전체
```

- 사용자 ID / 기기 ID / 서버 주소 / 관리자 토큰은 `AsyncStorage` 에 저장되어
  다음 실행 때는 첫 화면을 건너뛰고 사용자 페이지로 바로 들어간다.
- 기기 ID 는 ESP32 칩의 MAC 에서 자동 생성된다. 첫 화면에서 **연결된 기기 찾기** 를 누르면
  방금 신호를 보낸 기기가 목록에 뜨고, 눌러서 등록한다(직접 입력도 가능).

## 차트

`src/ui/charts.tsx` — `react-native-svg` 로 직접 그린다.
색은 명/암 모드별로 대비를 검증한 값을 쓰고(파랑 = 계열, 아쿠아 = 최적),
"최적" 막대는 색과 함께 라벨을 붙여 색만으로 구분하지 않는다.

## 검사

```bash
npm run typecheck        # tsc --noEmit
npx expo export --platform android   # 번들 검증
```
