#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PentaAI Web Console - Thin Client
VERSION 5.6 - Mode Selection & Rich Aesthetics
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("PentaAI-UI")

app = FastAPI(title="PentaAI Web Console")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

AI_SERVER_PORT = 9090
UI_PORT = 8080

HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PentaAI Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0b0e14;--sf:#121620;--sf2:#1a2030;
  --bd:#232b3e;--bd2:#2d3a52;
  --ac:#4f9cf9;--ac2:#7c3aed;
  --gn:#22d3a5;--am:#f59e0b;--rd:#f87171;--pk:#f472b6;
  --tx:#e2e8f0;--tx2:#8899bb;--tx3:#4a5a7a;
  --mono:'JetBrains Mono',monospace;--sans:'Syne',sans-serif;
}
html,body{height:100%;background:var(--bg);color:var(--tx);font-family:var(--sans);overflow:hidden}
.app{display:grid;grid-template-columns:292px 1fr;grid-template-rows:52px 1fr;height:100vh}

.topbar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;background:var(--sf);border-bottom:1px solid var(--bd);z-index:10}
.logo{font-size:15px;font-weight:800;letter-spacing:-.02em}.logo span{color:var(--ac)}
.vtag{font-family:var(--mono);font-size:10px;color:var(--tx3);
  background:var(--sf2);border:1px solid var(--bd);padding:2px 8px;border-radius:4px}
.topbar-r{display:flex;align-items:center;gap:12px}
.backend-wrap{display:flex;align-items:center;gap:8px}
.backend-input{width:220px}
.conn{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;color:var(--tx2)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--gn);flex-shrink:0}
.dot.r{background:var(--rd)}.dot.a{background:var(--am);animation:pulse 1.5s infinite}

.sb{background:var(--sf);border-right:1px solid var(--bd);overflow-y:auto;display:flex;flex-direction:column}
.sb::-webkit-scrollbar{width:4px}
.sbs{padding:14px 16px;border-bottom:1px solid var(--bd)}
.slbl{font-family:var(--mono);font-size:9px;letter-spacing:.12em;color:var(--tx3);
  text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}

.scard{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:8px;transition:all .3s ease}
.srow{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.snm{font-family:var(--mono);font-size:11px;color:var(--tx2)}
.pill{font-family:var(--mono);font-size:9px;padding:2px 7px;border-radius:20px;font-weight:700;letter-spacing:.05em}
.ok{background:rgba(34,211,165,.15);color:var(--gn);border:1px solid rgba(34,211,165,.3)}
.err{background:rgba(248,113,113,.15);color:var(--rd);border:1px solid rgba(248,113,113,.3)}

.hbars{display:flex;flex-direction:column;gap:6px}
.hrow{display:flex;align-items:center;gap:8px}
.hnm{font-family:var(--mono);font-size:9px;color:var(--tx3);width:82px;flex-shrink:0}
.htr{flex:1;height:4px;background:var(--bd);border-radius:2px;overflow:hidden}
.hfi{height:100%;border-radius:2px;transition:width .7s ease}
.hv{font-family:var(--mono);font-size:9px;color:var(--tx3);width:32px;text-align:right}

.embg{display:inline-flex;align-items:center;gap:6px;background:var(--sf2);
  border:1px solid var(--bd2);border-radius:20px;padding:3px 10px;
  font-family:var(--mono);font-size:10px;color:var(--ac)}

.chat{display:flex;flex-direction:column;overflow:hidden}
.msgs{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px}
.msg{display:flex;gap:10px;animation:mIn .25s ease-out}
.msg.u{flex-direction:row-reverse}
.av{width:30px;height:30px;border-radius:8px;flex-shrink:0;display:flex;
  align-items:center;justify-content:center;font-size:12px;font-weight:700}
.msg.ai .av{background:rgba(79,156,249,.15);color:var(--ac);border:1px solid rgba(79,156,249,.2)}
.msg.u .av{background:rgba(124,58,237,.15);color:var(--ac2);border:1px solid rgba(124,58,237,.2)}
.mb{max-width:72%;display:flex;flex-direction:column;gap:4px}
.bbl{padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.6;word-break:break-word}
.msg.ai .bbl{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);border-radius:4px 12px 12px 12px}
.msg.u  .bbl{background:linear-gradient(135deg,#2563eb,#4f46e5);color:white;border-radius:12px 4px 12px 12px}
.mm{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:9px;color:var(--tx3)}

.inpbar{padding:16px 24px;background:var(--sf);border-top:1px solid var(--bd);display:flex;gap:10px;align-items:flex-end}
textarea#inp{width:100%;background:var(--sf2);border:1px solid var(--bd2);border-radius:10px;padding:11px 14px;color:var(--tx);font-family:var(--sans);font-size:14px;resize:none;min-height:44px;max-height:120px;outline:none;line-height:1.5;transition:border-color .3s}
.sndbtn{width:44px;height:44px;border-radius:10px;background:var(--ac);border:none;color:white;cursor:pointer;transition:all .3s}

/* Switch UI */
.sw {position:relative;display:inline-block;width:34px;height:20px}
.sw input {opacity:0;width:0;height:0}
.sl {position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:var(--bd);transition:.4s;border-radius:20px}
.sl:before {position:absolute;content:"";height:14px;width:14px;left:3px;bottom:3px;background-color:white;transition:.4s;border-radius:50%}
input:checked + .sl {background-color:var(--ac2)}
input:checked + .sl:before {transform:translateX(14px)}

.modal{background:var(--sf);border:1px solid var(--bd2);border-radius:16px;padding:24px;width:480px}
.mtitle{font-size:16px;font-weight:800;color:var(--tx);margin-bottom:16px;display:flex;align-items:center;gap:8px}
.bsv{background:var(--ac);border:none;color:white;border-radius:6px;padding:6px 14px;cursor:pointer}
.pinp{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);padding:6px 10px;border-radius:6px;outline:none}

@keyframes mIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
/* Admin Control Panel */
.ctrl-tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--bd);padding-bottom:12px}
.ctab{background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:6px;padding:6px 14px;cursor:pointer;font-family:var(--mono);font-size:11px;transition:all .2s}
.ctab.active{background:var(--ac2);border-color:var(--ac2);color:white}
.cpanel{display:none}.cpanel.active{display:block}
.conn-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.conn-btn{background:var(--sf2);border:1px solid var(--bd2);color:var(--tx2);border-radius:8px;padding:10px;cursor:pointer;font-family:var(--mono);font-size:11px;transition:all .2s;text-align:center}
.conn-btn:hover{border-color:var(--ac);color:var(--ac)}
.conn-btn.active-mode{border-color:var(--gn);color:var(--gn);background:rgba(34,211,165,.08)}
.ping-result{font-family:var(--mono);font-size:10px;background:var(--sf2);border:1px solid var(--bd);border-radius:6px;padding:10px;min-height:60px;color:var(--tx2);margin-top:8px}
.test-out{font-family:var(--mono);font-size:10px;background:#080c12;border:1px solid var(--bd);border-radius:8px;padding:12px;min-height:180px;max-height:280px;overflow-y:auto;color:var(--gn);white-space:pre-wrap;margin-top:8px}
.mon-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.mstat{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;padding:10px}
.mst-lbl{font-family:var(--mono);font-size:9px;color:var(--tx3);margin-bottom:4px;text-transform:uppercase;letter-spacing:.08em}
.mst-val{font-family:var(--mono);font-size:14px;font-weight:700;color:var(--ac)}
.mst-sub{font-family:var(--mono);font-size:9px;color:var(--tx3);margin-top:2px}
.cb-bar{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:10px;margin-top:4px}
.cb-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
</style>
</head>
<body>
<div class="app">
<header class="topbar">
  <div style="display:flex;align-items:center;gap:10px">
    <div class="logo">Penta<span>AI</span> 🛰️</div>
    <span class="vtag">v5.6 ModeUI</span>
  </div>
  <div class="topbar-r">
    <div class="backend-wrap">
      <input type="text" id="backend-url" class="pinp backend-input" placeholder="Backend URL (http://IP:9090)">
      <button class="bsv" style="font-size:10px" onclick="applyBackend()">🔌 Connect</button>
    </div>
    <input type="password" id="auth-token" class="pinp" placeholder="Token..." style="width:100px;font-size:10px" value="12345abcde">
    <button class="bsv" style="font-size:10px" onclick="openConfig()">⚙️ Cloud</button>
    <button class="bsv" style="font-size:10px" onclick="openRuntimeConfig()">🧩 System</button>
    <button class="bsv" style="font-size:10px;background:var(--ac2)" onclick="openControl()">🔗 Kết nối</button>
    <div class="conn"><div class="dot" id="conn-dot"></div><span id="conn-txt">Kết nối...</span></div>
  </div>
</header>

<aside class="sb">
  <div class="sbs">
    <div class="slbl">Hệ thống <button class="bsv" style="padding:2px 8px" onclick="refreshHealth()">↻</button></div>
    <div class="scard">
      <div class="srow"><span class="snm">AI</span><span class="pill" id="p-ai">...</span></div>
      <div class="srow"><span class="snm">Tâm trạng</span><div class="embg"><span id="em-ic">🌙</span><span id="em-tx">—</span></div></div>
    </div>
  </div>

  <div class="sbs">
    <div class="slbl">Chế độ hoạt động</div>
    <div class="scard" id="mode-card" style="border-color:var(--ac)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span id="mode-lbl" style="font-size:11px;color:var(--ac);font-weight:800">💬 TRÒ CHUYỆN</span>
        <label class="sw">
          <input type="checkbox" id="mode-toggle" onchange="toggleMode()">
          <span class="sl"></span>
        </label>
      </div>
      <p style="font-size:9px;color:var(--tx3);line-height:1.4">Gạt để chuyển sang <b>Điều khiển (CMD)</b> trực tiếp Windows.</p>
    </div>
  </div>

  <div class="sbs">
    <div class="slbl">Hormone</div>
    <div class="hbars" id="h-bars"></div>
  </div>

  <div class="sbs">
    <div class="slbl">Âm thanh</div>
    <div style="display:flex;align-items:center;justify-content:space-between">
      <span style="font-size:11px;color:var(--tx2)">Bật TTS</span>
      <input type="checkbox" id="tts-on" checked>
    </div>
  </div>
</aside>

<main class="chat">
  <div class="msgs" id="msgs"></div>
  <div class="inpbar">
    <textarea id="inp" rows="1" placeholder="Nhắn tin nà..."></textarea>
    <button class="sndbtn" onclick="send()">➤</button>
  </div>
</main>
</div>

<!-- ═══ ADMIN CONTROL PANEL ══════════════════════════════════════════════ -->
<div id="ctrl-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:102;align-items:center;justify-content:center">
  <div class="modal" style="width:min(520px,94vw)">
    <div class="mtitle">🔗 Kết nối PentaKuru
      <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 10px;cursor:pointer" onclick="closeControl()">✕</button>
    </div>
    <p style="font-family:var(--mono);font-size:10px;color:var(--tx2);margin-bottom:14px;line-height:1.6">
      Chọn cách AI server kết nối tới <b>PentaKuru</b> trên Windows. Áp dụng ngay, không cần restart.
    </p>
    <div class="conn-grid">
      <button class="conn-btn" id="cbtn-cloudflare" onclick="setConnMode('cloudflare')">☁️ Cloudflare Tunnel<br><span style="font-size:9px;color:var(--tx3)">Qua internet, không cần cùng mạng</span></button>
      <button class="conn-btn" id="cbtn-tailscale" onclick="setConnMode('tailscale')">🔒 Tailscale VPN<br><span style="font-size:9px;color:var(--tx3)">Peer-to-peer, nhanh hơn Cloudflare</span></button>
      <button class="conn-btn" id="cbtn-lan" onclick="setConnMode('lan')">🏠 LAN Direct<br><span style="font-size:9px;color:var(--tx3)">Cùng mạng Wi-Fi/LAN, trễ thấp nhất</span></button>
      <button class="conn-btn" id="cbtn-all" onclick="setConnMode('all')">⚡ Auto Fallback<br><span style="font-size:9px;color:var(--tx3)">Cloudflare → Tailscale → LAN</span></button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:10px">
      <button class="bsv" style="font-size:10px" onclick="pingAll()">🏓 Kiểm tra kết nối</button>
      <button class="bsv" style="font-size:10px;background:var(--sf2);color:var(--tx2);border:1px solid var(--bd2)" onclick="reloadConfig()">↺ Reload Config</button>
    </div>
    <div class="ping-result" id="ping-result">— Nhấn "Kiểm tra kết nối" để test —</div>
  </div>
</div>

<div id="config-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center">
  <div class="modal">
    <div class="mtitle">⚙️ Cài đặt Cloud <button style="margin-left:auto" onclick="closeConfig()">✕</button></div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <input class="pinp" id="cfg-url" type="text" placeholder="URL API">
      <input class="pinp" id="cfg-key" type="password" placeholder="API Key">
      <input class="pinp" id="cfg-mod" type="text" placeholder="Model">
      <button class="bsv" onclick="saveConfig()">Lưu</button>
    </div>
  </div>
</div>

<div id="runtime-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:101;align-items:center;justify-content:center">
  <div class="modal" style="width:min(860px,92vw)">
    <div class="mtitle">🧩 Cài đặt hệ thống (runtime)
      <button style="margin-left:auto" onclick="closeRuntimeConfig()">✕</button>
    </div>
    <p style="font-family:var(--mono);font-size:10px;color:var(--tx2);margin-bottom:10px">
      Chỉnh trực tiếp cấu hình AI server. Không cần sửa code. Nhấn Save để áp dụng runtime.
    </p>
    <textarea id="runtime-json" style="width:100%;min-height:320px;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);padding:10px;border-radius:8px;font-family:var(--mono);font-size:11px;outline:none"></textarea>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">
      <button class="bsv" onclick="loadRuntimeConfig()">Reload</button>
      <button class="bsv" onclick="saveRuntimeConfig()">Save Runtime</button>
    </div>
  </div>
</div>

<script>
const DEFAULT_BACKEND = `http://${location.hostname}:9090`;
let BACKEND = localStorage.getItem('penta_backend_url') || DEFAULT_BACKEND;
let WS_BACKEND = BACKEND.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws/chat';

let ws, wsOk = false, audioQ = [], playing = false, currentMode = 'chat';
const getToken = () => document.getElementById('auth-token').value;

function applyBackend() {
  const input = document.getElementById('backend-url');
  const raw = (input.value || '').trim();
  if (!raw) return;
  if (!/^https?:\/\//i.test(raw)) {
    appendSys('⚠️ URL phải bắt đầu bằng http:// hoặc https://');
    return;
  }
  BACKEND = raw.replace(/\/$/, '');
  WS_BACKEND = BACKEND.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws/chat';
  localStorage.setItem('penta_backend_url', BACKEND);
  appendSys(`--- Đổi backend sang ${BACKEND} ---`);
  if (ws) {
    try { ws.close(); } catch(e) {}
  }
  connect();
}

function toggleMode() {
    const isCmd = document.getElementById('mode-toggle').checked;
    currentMode = isCmd ? 'cmd' : 'chat';
    const lbl = document.getElementById('mode-lbl'), card = document.getElementById('mode-card'), btn = document.querySelector('.sndbtn'), inp = document.getElementById('inp');
    if (isCmd) {
        lbl.textContent = '⚡ ĐIỀU KHIỂN (CMD)'; lbl.style.color = 'var(--ac2)'; card.style.borderColor = 'var(--ac2)';
        btn.style.background = 'var(--ac2)'; inp.style.borderColor = 'var(--ac2)';
        appendSys('--- CHẾ ĐỘ ĐIỀU KHIỂN WINDOWS KÍCH HOẠT ---');
    } else {
        lbl.textContent = '💬 TRÒ CHUYỆN'; lbl.style.color = 'var(--ac)'; card.style.borderColor = 'var(--ac)';
        btn.style.background = 'var(--ac)'; inp.style.borderColor = 'var(--bd2)';
        appendSys('--- QUAY LẠI CHẾ ĐỘ TRÒ CHUYỆN ---');
    }
}

function connect() {
    const token = encodeURIComponent(getToken() || '');
    const wsUrl = token ? `${WS_BACKEND}?token=${token}` : WS_BACKEND;
    ws = new WebSocket(wsUrl);
  ws.onopen = () => { wsOk = true; setConn(true); refreshHealth(); appendSys(`WS connected: ${wsUrl}`); };
    ws.onclose = () => { wsOk = false; setConn(false); setTimeout(connect, 3000); };
    ws.onmessage = e => {
        const d = JSON.parse(e.data);
        if (d.type === 'response') {
          appendAI(d.text, d.ai_latency_ms, d.emotional_state, d.pipeline, d.mode_used);
            if (d.emotional_state) setEmotion(d.emotional_state);
            if (d.hormone_levels) drawHormones(d.hormone_levels);
        } else if (d.type === 'audio_chunk') {
            playChunk(d.audio_b64, d.mime_type);
        } else if (d.type === 'error') {
            appendSys('⚠️ ' + d.msg);
        }
    };
}

function playChunk(b64, mimeType = 'audio/wav') {
    const bin = atob(b64), arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    audioQ.push(URL.createObjectURL(new Blob([arr], { type: mimeType })));
    if (!playing) processQ();
}
async function processQ() {
    if (!audioQ.length) { playing = false; return; }
    playing = true;
    const url = audioQ.shift(), a = new Audio(url);
    a.onended = () => { URL.revokeObjectURL(url); processQ(); };
    a.onerror = () => { URL.revokeObjectURL(url); processQ(); };
    try { await a.play(); } catch (e) { processQ(); }
}

function send() {
    const ta = document.getElementById('inp'), text = ta.value.trim();
    if (!text || !wsOk) return;
    appendUser(text); ta.value = '';
  ws.send(JSON.stringify({ text, tts: document.getElementById('tts-on').checked, token: getToken(), mode: currentMode, speaker: 'NF', speed: 1.0 }));
}

function setConn(ok) {
    document.getElementById('conn-dot').className = 'dot' + (ok ? '' : ' r');
  document.getElementById('conn-txt').textContent = ok ? 'WS sẵn sàng' : 'Mất kết nối';
}

async function refreshHealth() {
    try {
        const res = await fetch(`${BACKEND}/api/health`, { headers: {'Authorization': `Bearer ${getToken()}`} });
        const d = await res.json();
        document.getElementById('p-ai').className = 'pill ' + (d.ai_ready ? 'ok' : 'err');
        document.getElementById('p-ai').textContent = d.ai_ready ? 'OK' : 'LỖI';
        if (d.emotional_state) setEmotion(d.emotional_state);
        if (d.hormone_levels) drawHormones(d.hormone_levels);
    } catch (e) {}
}

function setEmotion(s) { document.getElementById('em-ic').textContent = '😊'; document.getElementById('em-tx').textContent = s; }
function drawHormones(lvl) {
    const c = document.getElementById('h-bars'); c.innerHTML = '';
    Object.entries(lvl || {}).forEach(([h, v]) => {
        const pct = Math.min(100, Math.round(v / 1.5 * 100));
        c.innerHTML += `<div class="hrow"><span class="hnm">${h}</span><div class="htr"><div class="hfi" style="width:${pct}%;background:var(--ac)"></div></div><span class="hv">${v.toFixed(2)}</span></div>`;
    });
}

function appendUser(t) {
    const d = document.createElement('div'); d.className = 'msg u';
    d.innerHTML = `<div class="av">ME</div><div class="mb"><div class="bbl">${t}</div></div>`;
    document.getElementById('msgs').appendChild(d); document.getElementById('msgs').scrollTop = 99999;
}
function appendAI(t, ms, em, pipeline, modeUsed) {
    const d = document.createElement('div'); d.className = 'msg ai';
    const meta = [
      `${ms || 0}ms`,
      em || '',
      modeUsed ? `mode:${modeUsed}` : '',
      pipeline ? `pipe:${pipeline}` : ''
    ].filter(Boolean).join(' · ');
    d.innerHTML = `<div class="av">AI</div><div class="mb"><div class="bbl">${t}</div><div class="mm">${meta}</div></div>`;
    document.getElementById('msgs').appendChild(d); document.getElementById('msgs').scrollTop = 99999;
}
function appendSys(t) {
    const d = document.createElement('div'); d.style = 'font-family:var(--mono);font-size:9px;color:var(--tx3);text-align:center;margin:10px 0';
    d.textContent = t; document.getElementById('msgs').appendChild(d); document.getElementById('msgs').scrollTop = 99999;
}

function openConfig() { document.getElementById('config-bg').style.display = 'flex'; }
function closeConfig() { document.getElementById('config-bg').style.display = 'none'; }
async function saveConfig() {
    const data = { url: document.getElementById('cfg-url').value, key: document.getElementById('cfg-key').value, model: document.getElementById('cfg-mod').value };
    await fetch(`${BACKEND}/api/config_cloud`, { method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}`}, body: JSON.stringify(data) });
    closeConfig();
}

function openRuntimeConfig() {
  document.getElementById('runtime-bg').style.display = 'flex';
  loadRuntimeConfig();
}
function closeRuntimeConfig() { document.getElementById('runtime-bg').style.display = 'none'; }

async function loadRuntimeConfig() {
  try {
    const res = await fetch(`${BACKEND}/api/config_runtime`, {
      headers: {'Authorization': `Bearer ${getToken()}`}
    });
    const data = await res.json();
    const cfg = data.config || {};
    document.getElementById('runtime-json').value = JSON.stringify(cfg, null, 2);
  } catch (e) {
    appendSys('⚠️ Không tải được runtime config');
  }
}

async function saveRuntimeConfig() {
  try {
    const text = document.getElementById('runtime-json').value;
    const parsed = JSON.parse(text);
    const res = await fetch(`${BACKEND}/api/config_runtime`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`
      },
      body: JSON.stringify({config: parsed})
    });
    const out = await res.json();
    if (out.status === 'ok') {
      appendSys('✅ Runtime config đã lưu và áp dụng');
      closeRuntimeConfig();
      refreshHealth();
    } else {
      appendSys('⚠️ Lưu config lỗi: ' + (out.message || 'unknown'));
    }
  } catch (e) {
    appendSys('⚠️ JSON không hợp lệ hoặc lưu thất bại');
  }
}

document.getElementById('backend-url').value = BACKEND;
document.getElementById('inp').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
connect();

// ═══ ADMIN CONTROL PANEL ════════════════════════════════════════════════════

let monTimer = null;
let _currentConnMode = 'all';

function openControl() {
  document.getElementById('ctrl-bg').style.display = 'flex';
  _highlightConnBtn(_currentConnMode);
}
function closeControl() {
  document.getElementById('ctrl-bg').style.display = 'none';
}

// ── 1. CONNECT ──────────────────────────────────────────────────────────────
function _highlightConnBtn(mode) {
  ['cloudflare','tailscale','lan','all'].forEach(m => {
    const b = document.getElementById('cbtn-' + m);
    if (b) b.classList.toggle('active-mode', m === mode);
  });
}
async function setConnMode(mode) {
  try {
    const r = await fetch(`${BACKEND}/admin/connect`, {
      method: 'POST',
      headers: {'Content-Type':'application/json','Authorization':`Bearer ${getToken()}`},
      body: JSON.stringify({mode})
    });
    const d = await r.json();
    _currentConnMode = mode;
    _highlightConnBtn(mode);
    const res = d.ping_results || {};
    let txt = `Mode: ${mode}\n`;
    Object.entries(res).forEach(([k,v]) => {
      const icon = v.ok ? '✅' : '❌';
      txt += `${icon} ${k}: ${v.ok ? v.latency_ms+'ms' : (v.error||'failed')}\n`;
    });
    if (d.applied) txt += `\nApplied: ${JSON.stringify(d.applied)}`;
    document.getElementById('ping-result').textContent = txt;
  } catch(e) {
    document.getElementById('ping-result').textContent = '⚠️ ' + e.message;
  }
}
async function pingAll() {
  document.getElementById('ping-result').textContent = 'Pinging...';
  await setConnMode('test');
  _highlightConnBtn(_currentConnMode);
}
async function reloadConfig() {
  try {
    const r = await fetch(`${BACKEND}/admin/reload_config`, {
      method:'POST',
      headers:{'Authorization':`Bearer ${getToken()}`,'Content-Type':'application/json'},
      body:'{}'
    });
    const d = await r.json();
    document.getElementById('ping-result').textContent = d.ok
      ? `✅ Config reloaded. Keys: ${d.key_count}`
      : '⚠️ ' + d.error;
  } catch(e) {
    document.getElementById('ping-result').textContent = '⚠️ ' + e.message;
  }
}

</script>
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

if __name__ == "__main__":
    import uvicorn
    log.info(f"🚀 PentaAI UI Client đang chạy tại http://0.0.0.0:{UI_PORT}")
    log.info(f"🔗 Đang trỏ về Backend: http://localhost:{AI_SERVER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
