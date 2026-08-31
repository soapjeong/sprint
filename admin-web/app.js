/* DormX 관리자 대시보드 — 사용자 앱과 공유하는 코드 없이 API 만 호출한다. */
'use strict';

const $ = (id) => document.getElementById(id);
const state = { server: '', token: '', users: [] };

const NOTE_LABEL = {
  alcohol: '음주',
  caffeine: '취침 6시간 이내 카페인',
  none: '없음',
  other: '기타',
};
const OUTCOME = {
  onset: { label: '입면 성공', color: 'var(--series-2)' },
  no_onset: { label: '미입면(60분)', color: 'var(--warning)' },
  running: { label: '진행 중', color: 'var(--accent)' },
  aborted: { label: '중단', color: 'var(--text-3)' },
  fault: { label: '안전 정지', color: 'var(--danger)' },
};

// ---------------------------------------------------------------- 유틸
function normalizeBase(url) {
  const trimmed = (url || '').trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

async function api(path) {
  const res = await fetch(normalizeBase(state.server) + path, {
    headers: { 'X-Admin-Token': state.token },
  });
  if (res.status === 401) throw new Error('관리자 토큰이 올바르지 않습니다.');
  if (!res.ok) {
    let detail = `요청 실패 (HTTP ${res.status})`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) { /* 본문이 JSON 이 아닐 수 있다 */ }
    throw new Error(detail);
  }
  return res.json();
}

function showError(message) {
  const box = $('error');
  box.textContent = message;
  box.hidden = !message;
}

function fmtDateTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
const fmtNum = (v, digits = 1) => (v === null || v === undefined ? '-' : Number(v).toFixed(digits));
const stars = (n) => (n ? `<span class="stars">${'★'.repeat(n)}${'☆'.repeat(5 - n)}</span>` : '<span class="muted">-</span>');

function statTile(label, value, unit) {
  return `<div class="stat"><div class="label">${label}</div>
    <div class="value">${value}${unit ? ` <small>${unit}</small>` : ''}</div></div>`;
}

function outcomeBadge(outcome) {
  const o = OUTCOME[outcome] || { label: outcome, color: 'var(--text-3)' };
  return `<span class="badge"><span class="dot" style="background:${o.color}"></span>${o.label}</span>`;
}

// ---------------------------------------------------------------- 차트
/**
 * 설정 온도별 평균 SOL — 단일 계열 막대차트.
 * 가장 성적이 좋은 온도는 색과 함께 "최적" 라벨을 붙여 색만으로 구분하지 않는다.
 */
function tempBarChart(bars) {
  if (!bars.length) return '<p class="hint">입면에 성공한 세션이 아직 없습니다.</p>';
  const W = 640, H = 220, PAD = 16, TOP = 22, BOTTOM = 30;
  const plotH = H - TOP - BOTTOM;
  const plotW = W - PAD * 2;
  const max = Math.max(...bars.map((b) => b.avg));
  const niceMax = Math.ceil((max * 1.15) / 5) * 5 || 10;
  const slot = plotW / bars.length;
  const barW = Math.max(10, Math.min(72, slot - 8));
  const bestIdx = bars.reduce((best, b, i) => (b.avg < bars[best].avg ? i : best), 0);

  const marks = bars.map((b, i) => {
    const h = Math.max(2, (b.avg / niceMax) * plotH);
    const x = PAD + i * slot + (slot - barW) / 2;
    const y = TOP + plotH - h;
    const isBest = i === bestIdx;
    const r = Math.min(4, barW / 2, h);
    const d = `M ${x} ${y + h} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y}
               L ${x + barW - r} ${y} Q ${x + barW} ${y} ${x + barW} ${y + r} L ${x + barW} ${y + h} Z`;
    return `
      <path d="${d}" fill="${isBest ? 'var(--series-2)' : 'var(--series-1)'}"></path>
      <text x="${x + barW / 2}" y="${y - 6}" text-anchor="middle" font-size="12"
            font-weight="${isBest ? 700 : 500}" fill="var(--text-2)">
        ${isBest ? `최적 ${b.avg.toFixed(0)}분` : `${b.avg.toFixed(0)}분`}
      </text>
      <text x="${x + barW / 2}" y="${H - 10}" text-anchor="middle" font-size="11" fill="var(--text-3)">
        ${b.temp.toFixed(1)}℃
      </text>
      <title>${b.temp.toFixed(1)}℃ · 평균 ${b.avg.toFixed(1)}분 · ${b.count}회</title>`;
  }).join('');

  return `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
         aria-label="설정 온도별 평균 잠들기 시간 막대 그래프">
      <line x1="${PAD}" x2="${W - PAD}" y1="${TOP + plotH}" y2="${TOP + plotH}" stroke="var(--grid)"></line>
      <text x="${PAD}" y="${TOP - 8}" font-size="11" fill="var(--text-3)">${niceMax}분</text>
      ${marks}
    </svg>
    <figcaption>막대에 마우스를 올리면 측정 횟수까지 보입니다.</figcaption>`;
}

// ---------------------------------------------------------------- 화면
function showSection(name) {
  $('login').hidden = name !== 'login';
  $('users').hidden = name !== 'users';
  $('detail').hidden = name !== 'detail';
  $('logout').hidden = name === 'login';
  $('server-label').textContent = name === 'login' ? '' : normalizeBase(state.server);
}

async function loadUsers() {
  showError('');
  const rows = await api('/api/admin/users');
  state.users = rows;
  const totals = rows.reduce(
    (acc, r) => ({
      sessions: acc.sessions + r.session_count,
      onsets: acc.onsets + r.onset_count,
    }),
    { sessions: 0, onsets: 0 },
  );
  $('totals').innerHTML =
    statTile('등록 사용자', rows.length, '명') +
    statTile('누적 세션', totals.sessions, '회') +
    statTile('입면 성공', totals.onsets, '회');

  $('user-rows').innerHTML = rows.length
    ? rows.map((r) => `
        <tr class="clickable" data-user="${r.user_id}">
          <td>${r.user_id}</td>
          <td>${r.name || '<span class="muted">-</span>'}</td>
          <td class="num">${r.session_count}</td>
          <td class="num">${r.onset_count}</td>
          <td class="num">${fmtNum(r.avg_sol_min)}</td>
          <td class="num">${r.avg_rating ? Number(r.avg_rating).toFixed(1) : '-'}</td>
          <td class="num">${r.device_count}</td>
          <td>${fmtDateTime(r.last_session_at)}</td>
        </tr>`).join('')
    : '<tr><td colspan="8" class="muted">아직 등록된 사용자가 없습니다.</td></tr>';

  document.querySelectorAll('#user-rows tr.clickable').forEach((tr) => {
    tr.addEventListener('click', () => loadDetail(tr.dataset.user));
  });
  showSection('users');
}

async function loadDetail(userId) {
  showError('');
  const data = await api(`/api/admin/users/${encodeURIComponent(userId)}`);
  const sessions = data.sessions;
  const onsets = sessions.filter((s) => s.outcome === 'onset' && s.sol_min !== null);
  const rated = sessions.filter((s) => s.rating);
  const avgSol = onsets.length ? onsets.reduce((a, s) => a + s.sol_min, 0) / onsets.length : null;
  const avgRating = rated.length ? rated.reduce((a, s) => a + s.rating, 0) / rated.length : null;

  $('detail-title').textContent = `${data.user.user_id}${data.user.name ? ` · ${data.user.name}` : ''}`;
  $('detail-stats').innerHTML =
    statTile('세션', sessions.length, '회') +
    statTile('입면 성공', onsets.length, '회') +
    statTile('평균 SOL', fmtNum(avgSol), '분') +
    statTile('평균 별점', avgRating ? avgRating.toFixed(1) : '-', '/ 5');
  $('detail-devices').innerHTML = data.devices.length
    ? data.devices.map((d) => `<div class="hint">기기 ${d.device_id}${d.label ? ` (${d.label})` : ''}
        · 마지막 통신 ${fmtDateTime(d.last_seen_at)}</div>`).join('')
    : '<div class="hint">등록된 기기가 없습니다.</div>';

  const byTemp = new Map();
  onsets.forEach((s) => {
    if (s.target_temp_c === null) return;
    const cur = byTemp.get(s.target_temp_c) || { sum: 0, count: 0 };
    byTemp.set(s.target_temp_c, { sum: cur.sum + s.sol_min, count: cur.count + 1 });
  });
  const bars = [...byTemp.entries()]
    .map(([temp, v]) => ({ temp, avg: v.sum / v.count, count: v.count }))
    .sort((a, b) => a.temp - b.temp);
  $('temp-chart').innerHTML = tempBarChart(bars);

  $('session-rows').innerHTML = sessions.length
    ? sessions.map((s) => `
        <tr>
          <td class="num">${s.session_id}</td>
          <td>${fmtDateTime(s.started_at)}</td>
          <td>${outcomeBadge(s.outcome)}</td>
          <td class="num">${fmtNum(s.target_temp_c)}</td>
          <td class="num">${fmtNum(s.sol_min)}</td>
          <td class="num">${fmtNum(s.resting_bpm, 0)}</td>
          <td class="num">${fmtNum(s.threshold_bpm, 0)}</td>
          <td>${stars(s.rating)}</td>
          <td>${s.note_code ? (NOTE_LABEL[s.note_code] || s.note_code) +
              (s.note_code === 'other' && s.note_text ? ` (${s.note_text})` : '') : '<span class="muted">-</span>'}</td>
        </tr>`).join('')
    : '<tr><td colspan="9" class="muted">세션 데이터가 없습니다.</td></tr>';

  $('events').innerHTML = data.recent_events.slice(0, 20)
    .map((e) => `${fmtDateTime(e.recorded_at)} · ${e.flag}${e.v1 !== null ? ` (${Number(e.v1).toFixed(1)})` : ''}`)
    .join('<br>') || '기록된 이벤트가 없습니다.';

  $('export').onclick = () => downloadCsv(userId);
  showSection('detail');
}

async function downloadCsv(userId) {
  showError('');
  try {
    const res = await fetch(
      `${normalizeBase(state.server)}/api/admin/export/sessions.csv?user_id=${encodeURIComponent(userId)}`,
      { headers: { 'X-Admin-Token': state.token } },
    );
    if (!res.ok) throw new Error(`내려받기 실패 (HTTP ${res.status})`);
    const blob = await res.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `sessions_${userId}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    showError(err.message);
  }
}

// ---------------------------------------------------------------- 진입
async function signIn() {
  state.server = $('server').value;
  state.token = $('token').value.trim();
  if (!state.token) return showError('관리자 토큰을 입력하세요.');
  $('signin').disabled = true;
  try {
    await loadUsers();
    sessionStorage.setItem('dormx.admin', JSON.stringify({ server: state.server, token: state.token }));
  } catch (err) {
    showError(err.message);
  } finally {
    $('signin').disabled = false;
  }
}

function signOut() {
  sessionStorage.removeItem('dormx.admin');
  state.token = '';
  $('token').value = '';
  showSection('login');
}

window.addEventListener('DOMContentLoaded', () => {
  // 같은 서버에서 열었다면 그 주소를 기본값으로 쓴다
  const sameOrigin = location.protocol.startsWith('http') ? location.origin : 'http://localhost:8000';
  $('server').value = sameOrigin;

  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem('dormx.admin') || 'null');
  } catch (_) { /* 저장값이 깨졌으면 무시한다 */ }
  if (saved) {
    $('server').value = saved.server;
    $('token').value = saved.token;
    state.server = saved.server;
    state.token = saved.token;
    loadUsers().catch((err) => {
      showError(err.message);
      showSection('login');
    });
  }

  $('signin').addEventListener('click', signIn);
  $('token').addEventListener('keydown', (e) => { if (e.key === 'Enter') signIn(); });
  $('logout').addEventListener('click', signOut);
  $('back').addEventListener('click', () => loadUsers().catch((err) => showError(err.message)));
});
