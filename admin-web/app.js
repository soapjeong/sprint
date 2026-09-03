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
const FAILURE_LABEL = {
  hr_high: '심박수가 안정심박수보다 높게 유지됨',
  motion: '움직임이 계속 감지됨',
  sensor: '센서 데이터 오류·수신 끊김',
  unknown: '원인 미상',
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
 * 사람별 "기기 사용 횟수 대비 입면 성공 비율" — 단일 계열 가로 막대.
 * 전체 평균은 점선 한 줄로 같이 그려 비교 기준을 준다(색만으로 구분하지 않음).
 */
function successRateChart(rows, overall) {
  const usable = rows.filter((r) => r.session_count > 0);
  if (!usable.length) return '<p class="hint">아직 기기 사용 기록이 없습니다.</p>';

  const ROW_H = 38, PAD_L = 92, PAD_R = 64, TOP = 10;
  const W = 640, H = TOP + usable.length * ROW_H + 26;
  const plotW = W - PAD_L - PAD_R;

  const bars = usable.map((r, i) => {
    const rate = r.onset_count / r.session_count;
    const y = TOP + i * ROW_H;
    const w = Math.max(2, rate * plotW);
    const label = `${Math.round(rate * 100)}% (${r.onset_count}/${r.session_count})`;
    return `
      <rect x="${PAD_L}" y="${y + 8}" width="${plotW}" height="18" rx="9" fill="var(--surface-alt)"></rect>
      <rect x="${PAD_L}" y="${y + 8}" width="${w}" height="18" rx="9" fill="var(--series-1)"></rect>
      <text x="${PAD_L - 10}" y="${y + 21}" text-anchor="end" font-size="13" fill="var(--text-2)">${r.user_id}</text>
      <text x="${PAD_L + plotW + 8}" y="${y + 21}" font-size="12" fill="var(--text-2)">${label}</text>
      <title>${r.user_id} · 기기 사용 ${r.session_count}회 중 입면 성공 ${r.onset_count}회</title>`;
  }).join('');

  const overallX = PAD_L + overall * plotW;
  return `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
         aria-label="사람별 기기 사용 대비 입면 성공 비율">
      ${bars}
      <line x1="${overallX}" x2="${overallX}" y1="${TOP}" y2="${TOP + usable.length * ROW_H}"
            stroke="var(--text-3)" stroke-width="1.5" stroke-dasharray="4 4"></line>
      <text x="${overallX}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--text-3)">
        전체 평균 ${Math.round(overall * 100)}%
      </text>
    </svg>
    <figcaption>막대에 마우스를 올리면 사용 횟수까지 보입니다.</figcaption>`;
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
  const overall = totals.sessions ? totals.onsets / totals.sessions : 0;
  $('totals').innerHTML =
    statTile('등록 사용자', state.users.length, '명') +
    statTile('전체 기기 사용', totals.sessions, '회') +
    statTile('입면 성공', totals.onsets, '회') +
    statTile('전체 입면 성공률', `${Math.round(overall * 100)}%`,
             `${totals.onsets}/${totals.sessions}`);
  $('rate-chart').innerHTML = successRateChart(state.users, overall);

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
  if (!sessions.length) return '<p class="muted">기기 사용 기록이 없습니다.</p>';
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
    const why = ok
      ? '<span class="muted">-</span>'
      : s.outcome === 'no_onset'
        ? (FAILURE_LABEL[s.failure_reason] || FAILURE_LABEL.unknown)
        : '<span class="muted">-</span>';
    return `
      <tr>
        <td class="num">${s.session_id}</td>
        <td>${verdict}</td>
        <td>${why}</td>
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
            <th>실패 원인</th>
            <th>시작 누른 시간</th>
            <th>입면 성공 시간</th>
            <th class="num">입면시간(분)</th>
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
        ${statTile('기기 사용', sessions.length, '회')}
        ${statTile('입면 성공', onsets.length, '회')}
        ${statTile('입면 성공률', sessions.length ? `${Math.round((onsets.length / sessions.length) * 100)}%` : '-',
                   `${onsets.length}/${sessions.length}`)}
        ${statTile('평균 입면시간', fmtNum(avgSol), '분')}
        ${statTile('평균 별점', avgRating ? avgRating.toFixed(1) : '-', '/ 5')}
      </div>
      <div style="margin-top:12px">
        ${data.devices.map((d) => `<div class="hint">기기 ${d.device_id}${d.label ? ` (${d.label})` : ''}
          · 연결 ${d.link_state || 'unknown'} · 마지막 통신 ${fmtDateTime(d.last_seen_at)}</div>`).join('')
          || '<div class="hint">등록된 기기가 없습니다.</div>'}
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">기기 사용 기록</h2>
      ${sessionTable(sessions)}
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
