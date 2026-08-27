#!/usr/bin/env bash
# 하드웨어 없이 PC(호스트)에서 펌웨어 로직만 검증한다.
#   - 안전 감시(이상 온도 5초 지속 시에만 FAULT)
#   - 안정심박수 캘리브레이션(20초 폐기 + 30초 평균)
#   - 입면 판정(기준 심박 이하 + 무동작 20분 유지)
#   - 60분 미입면 시 기기 종료
# 사용법: firmware/test/run_tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKETCH="$HERE/../sleep_temp_optimizer/sleep_temp_optimizer.ino"
BUILD="$HERE/build"
mkdir -p "$BUILD"

# setup()/loop() 는 테스트 main() 과 충돌하지 않도록 이름만 바꿔서 포함한다.
sed -e 's/^void setup() {/void sketch_setup() {/' \
    -e 's/^void loop() {/void sketch_loop() {/' \
    "$SKETCH" > "$BUILD/sketch_under_test.inc"

g++ -std=gnu++17 -Wall -Wextra -Wno-unused-parameter \
    -I"$HERE/stubs" -I"$BUILD" \
    -o "$BUILD/test_logic" "$HERE/test_logic.cpp" "$HERE/stubs.cpp"

"$BUILD/test_logic"
