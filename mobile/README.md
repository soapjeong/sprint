# DormX Sleep 모바일 앱 (Expo / React Native)

사용자 페이지와 관리자 페이지를 한 앱에서 운영한다.

## 실행

```bash
cd mobile
npm install
npx expo start          # Expo Go 앱으로 QR 스캔
```

첫 화면에서 서버 주소를 PC의 LAN IP(`http://192.168.0.x:8000`)로 입력한다.
`app.json` 의 `extra.defaultServerUrl` 을 바꾸면 기본값이 바뀐다.

## 화면 구성

```
app/
  index.tsx              첫 화면 — 서버 주소 → 사용자 ID 등록/로그인 → 기기 등록
  user/home.tsx          사용자 페이지 — 요약 지표, SOL 추이, 온도별 성적, 최근 세션
  user/session/[id].tsx  세션 상세 — 결과, 측정 요약, 기기 이벤트 타임라인
  admin/index.tsx        관리자 페이지 — 토큰 인증 후 ID별 데이터 현황
  admin/[userId].tsx     관리자 — 특정 ID의 기기·세션·이벤트 전체
```

- 사용자 ID / 기기 ID / 서버 주소 / 관리자 토큰은 `AsyncStorage` 에 저장되어
  다음 실행 때는 첫 화면을 건너뛰고 사용자 페이지로 바로 들어간다.
- 기기 ID 는 브리지 실행 시 `--device` 값과 같아야 데이터가 그 사용자에게 쌓인다.

## 차트

`src/ui/charts.tsx` — `react-native-svg` 로 직접 그린다.
색은 명/암 모드별로 대비를 검증한 값을 쓰고(파랑 = 계열, 아쿠아 = 최적),
"최적" 막대는 색과 함께 라벨을 붙여 색만으로 구분하지 않는다.

## 검사

```bash
npm run typecheck        # tsc --noEmit
npx expo export --platform android   # 번들 검증
```
