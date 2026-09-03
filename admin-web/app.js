/* DormX 관리자 대시보드 — 사용자 앱과 공유하는 코드 없이 API 만 호출한다. */
'use strict';

const $ = (id) => document.getElementById(id);
const state = { server: '', token: '', users: [], activeIndex: 0 };

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
  $('workspace').hidden = name !== 'workspace';
  $('logout').hidden = name === 'login';
  $('server-label').textContent = name === 'login' ? '' : normalizeBase(state.server);
}

/** 사용자별 탭 — 한 명씩 눌러가며 본다 */
function renderTabs() {
  $('tabs').innerHTML = state.users
    .map((u, i) => `
      <button class="tab" role="tab" data-user="${u.user_id}"
              aria-selected="${i === state.activeIndex}">
        ${u.user_id}<span class="count">${u.session_count}회</span>
      </button>`)
    .join('');
  document.querySelectorAll('#tabs .tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeIndex = state.users.findIndex((u) => u.user_id === btn.dataset.user);
      renderTabs();
      loadUser(btn.dataset.user);
    });
  });
}

async function loadUsers() {
  showError('');
  state.users = await api('/api/admin/users');
  const totals = state.users.reduce(
    (acc, r) => ({ sessions: acc.sessions + r.session_count, onsets: acc.onsets + r.onset_count }),
    { sessions: 0, onsets: 0 },
  );
  $('totals').innerHTML =
    statTile('등록 사용자', state.users.length, '명') +
    statTile('누적 세션', totals.sessions, '회') +
    statTile('입면 성공', totals.onsets, '회');

  showSection('workspace');
  if (state.users.length === 0) {
    $('tabs').innerHTML = '';
    $('user-panel').innerHTML = '<div class="card"><p class="muted">아직 등록된 사용자가 없습니다.</p></div>';
    return;
  }
  if (state.activeIndex >= state.users.length) state.activeIndex = 0;
  renderTabs();
  await loadUser(state.users[state.activeIndex].user_id);
}

/** 요구된 다섯 가지를 한 표에 담는다:
 *  1) 입면 성공 여부 2) start 누른 시간 3) 입면 성공 시간
 *  4) 사용자의 평점 및 특이사항 5) 목표 온도와 안정심박수 */
function sessionTable(sessions) {
  if (!sessions.length) return '<p class="muted">세션 기록이 없습니다.</p>';
  const rows = sessions.map((s) => {
    const ok = s.outcome === 'onset';
    const verdict = ok
      ? '<span class="outcome-yes">성공</span>'
      : s.outcome === 'no_onset'
        ? '<span class="outcome-no">실패(60분)</span>'
        : `<span class="outcome-etc">${OUTCOME[s.outcome] ? OUTCOME[s.outcome].label : s.outcome}</span>`;
    const note = s.note_code
      ? (NOTE_LABEL[s.note_code] || s.note_code) +
        (s.note_code === 'other' && s.note_text ? ` (${s.note_text})` : '')
      : '<span class="muted">-</span>';
    return `
      <tr>
        <td class="num">${s.session_id}</td>
        <td>${verdict}</td>
        <td>${fmtDateTime(s.started_at)}</td>
        <td>${ok ? fmtDateTime(s.onset_at) : '<span class="muted">-</span>'}</td>
        <td class="num">${ok ? fmtNum(s.sol_min) : '-'}</td>
        <td>${stars(s.rating)}</td>
        <td>${note}</td>
        <td class="num">${fmtNum(s.target_temp_c)}</td>
        <td class="num">${fmtNum(s.resting_bpm, 0)}</td>
      </tr>`;
  }).join('');
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="num">#</th>
            <th>입면 성공</th>
            <th>시작 누른 시간</th>
            <th>입면 성공 시간</th>
            <th class="num">SOL(분)</th>
            <th>평점</th>
            <th>특이사항</th>
            <th class="num">목표 온도(℃)</th>
            <th class="num">안정심박(BPM)</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function loadUser(userId) {
  showError('');
  $('user-panel').innerHTML = '<div class="card"><p class="hint">불러오는 중…</p></div>';
  const data = await api(`/api/admin/users/${encodeURIComponent(userId)}`);
  const sessions = data.sessions;
  const onsets = sessions.filter((s) => s.outcome === 'onset' && s.sol_min !== null);
  const rated = sessions.filter((s) => s.rating);
  const avgSol = onsets.length ? onsets.reduce((a, s) => a + s.sol_min, 0) / onsets.length : null;
  const avgRating = rated.length ? rated.reduce((a, s) => a + s.rating, 0) / rated.length : null;

  const byTemp = new Map();
  onsets.forEach((s) => {
    if (s.target_temp_c === null) return;
    const cur = byTemp.get(s.target_temp_c) || { sum: 0, count: 0 };
    byTemp.set(s.target_temp_c, { sum: cur.sum + s.sol_min, count: cur.count + 1 });
  });
  const bars = [...byTemp.entries()]
    .map(([temp, v]) => ({ temp, avg: v.sum / v.count, count: v.count }))
    .sort((a, b) => a.temp - b.temp);

  $('user-panel').innerHTML = `
    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:flex-start">
        <div>
          <h2 style="margin:0 0 6px">${data.user.user_id}${data.user.name && data.user.name !== data.user.user_id ? ` · ${data.user.name}` : ''}</h2>
          <p class="hint" style="margin:0">가입 ${fmtDateTime(data.user.created_at)}</p>
        </div>
        <button id="export" class="secondary">CSV 내려받기</button>
      </div>
      <div class="stats" style="margin-top:14px">
        ${statTile('세션', sessions.length, '회')}
        ${statTile('입면 성공', onsets.length, '회')}
        ${statTile('평균 SOL', fmtNum(avgSol), '분')}
        ${statTile('평균 별점', avgRating ? avgRating.toFixed(1) : '-', '/ 5')}
      </div>
      <div style="margin-top:12px">
        ${data.devices.map((d) => `<div class="hint">기기 ${d.device_id}${d.label ? ` (${d.label})` : ''}
          · 연결 ${d.link_state || 'unknown'} · 마지막 통신 ${fmtDateTime(d.last_seen_at)}</div>`).join('')
          || '<div class="hint">등록된 기기가 없습니다.</div>'}
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">세션 기록</h2>
      ${sessionTable(sessions)}
    </div>

    <div class="card">
      <h2 style="margin-top:0">설정 온도별 평균 잠들기 시간</h2>
      <figure>${tempBarChart(bars)}</figure>
    </div>`;

  const button = document.getElementById('export');
  if (button) button.onclick = () => downloadCsv(userId);
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
});
