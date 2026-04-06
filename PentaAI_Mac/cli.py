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
from fastapi.responses import HTMLResponse, JSONResponse
import json

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
/* VoiceVox test panel */
.spk-list{max-height:180px;overflow-y:auto;display:flex;flex-direction:column;gap:4px;margin:10px 0}
.spk-item{display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--sf2);border:1px solid var(--bd);border-radius:6px;cursor:pointer;transition:all .2s;font-family:var(--mono);font-size:10px}
.spk-item:hover,.spk-item.sel{border-color:var(--ac);color:var(--ac)}
.spk-item .sid{background:var(--bd2);border-radius:4px;padding:1px 6px;color:var(--am);font-size:9px;flex-shrink:0}
.spk-search{width:100%;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);padding:6px 10px;border-radius:6px;outline:none;font-family:var(--mono);font-size:11px;margin-bottom:6px}
.reset-pill{display:inline-flex;align-items:center;gap:6px;background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.3);color:var(--rd);border-radius:8px;padding:8px 12px;font-family:var(--mono);font-size:10px;cursor:pointer;width:100%;justify-content:center;transition:all .2s}
.reset-pill:hover{background:rgba(248,113,113,.2)}

/* Wiki keyword suggestion chips */
.wiki-chips{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0 2px}
.wiki-chip{background:rgba(79,156,249,.12);border:1px solid rgba(79,156,249,.35);color:var(--ac);
  border-radius:16px;padding:3px 10px;font-family:var(--mono);font-size:10px;cursor:pointer;transition:all .2s}
.wiki-chip:hover{background:rgba(79,156,249,.25);border-color:var(--ac)}

/* Help modal */
.help-modal{background:var(--sf);border:1px solid var(--bd2);border-radius:16px;width:min(720px,95vw);max-height:88vh;display:flex;flex-direction:column}
.help-header{padding:20px 24px 14px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:10px;flex-shrink:0}
.help-body{overflow-y:auto;padding:20px 24px;flex:1}
.help-body::-webkit-scrollbar{width:4px}
.help-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px}
.htab{background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:20px;padding:5px 13px;cursor:pointer;font-family:var(--mono);font-size:10px;transition:all .2s;display:flex;align-items:center;gap:4px}
.htab.active{background:var(--sf2);border-color:var(--bd2);color:var(--tx)}
.help-section{display:none}.help-section.active{display:block}
.help-section-title{font-size:13px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:7px}
.help-row{display:grid;grid-template-columns:220px 1fr;gap:10px;padding:9px 0;border-bottom:1px solid var(--bd)}
.help-row:last-child{border-bottom:none}
.hcmd{font-family:var(--mono);font-size:11px;font-weight:600;padding:3px 8px;border-radius:5px;background:var(--sf2);border:1px solid var(--bd2);color:var(--ac);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;align-self:start}
.hdesc{font-size:12px;color:var(--tx2);line-height:1.6;align-self:center}
.help-search{width:100%;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);padding:8px 12px;border-radius:8px;outline:none;font-family:var(--mono);font-size:11px;margin-bottom:14px}
.no-result{font-family:var(--mono);font-size:11px;color:var(--tx3);text-align:center;padding:24px}
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
    <button class="bsv" style="font-size:10px;background:#1a2030;border:1px solid #2d3a52;width:32px;padding:0;border-radius:50%;font-size:15px" onclick="openHelp()" title="Hướng dẫn sử dụng">❓</button>
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
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <span style="font-size:11px;color:var(--tx2)">Bật TTS</span>
      <input type="checkbox" id="tts-on" checked>
    </div>
    <div style="margin-bottom:8px">
      <div style="font-family:var(--mono);font-size:9px;color:var(--tx3);margin-bottom:4px">🇻🇳 Giọng Valtec mặc định</div>
      <div style="display:flex;gap:5px;align-items:center">
        <select id="valtec-spk" style="flex:1;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);border-radius:6px;padding:3px 6px;font-family:var(--mono);font-size:10px">
          <option value="NF">NF – Nữ Bắc</option>
          <option value="NN">NN – Nam Bắc</option>
          <option value="SF">SF – Nữ Nam</option>
          <option value="SN">SN – Nam Nam</option>
        </select>
        <input id="valtec-spd" type="number" min="0.5" max="2.0" step="0.1" value="1.0"
          style="width:52px;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);border-radius:6px;padding:3px 5px;font-family:var(--mono);font-size:10px" title="Tốc độ">
        <button class="bsv" style="font-size:9px;padding:4px 8px" onclick="saveValtecDefault()" title="Lưu làm mặc định">💾</button>
      </div>
      <span id="valtec-save-st" style="font-family:var(--mono);font-size:9px;color:var(--tx3)"></span>
    </div>
    <button class="bsv" style="width:100%;font-size:10px;background:var(--sf2);color:var(--tx2);border:1px solid var(--bd2)" onclick="openVoiceTest()">
      🎌 Test giọng Nhật (VoiceVox)
    </button>
  </div>

  <div class="sbs">
    <div class="slbl">Hệ thống</div>
    <button class="reset-pill" onclick="openResetAI()">
      🔄 Reset AI sau nâng cấp
    </button>
  </div>

  <div class="sbs">
    <div class="slbl">📧 Gmail Notification</div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <span style="font-size:11px;color:var(--tx2)">Bật thông báo</span>
      <input type="checkbox" id="gmail-on" onchange="toggleGmailNotif()">
    </div>
    <button class="bsv" style="width:100%;font-size:10px;margin-bottom:6px" onclick="openGmailWhitelist()">
      ⚙️ Quản lí danh sách
    </button>
    <div id="gmail-queue-info" style="font-size:9px;color:var(--tx3);padding:6px;background:var(--sf2);border-radius:6px;display:none">
      <div>📋 Hàng đợi: <span id="gmail-queue-count">0</span></div>
      <div id="gmail-queue-items" style="margin-top:4px"></div>
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

<!-- ═══ VOICEVOX VOICE TEST ════════════════════════════════════════════════ -->
<div id="vtest-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:110;align-items:center;justify-content:center">
  <div class="modal" style="width:min(540px,94vw)">
    <div class="mtitle">🎌 Test giọng VoiceVox
      <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 10px;cursor:pointer" onclick="closeVoiceTest()">✕</button>
    </div>
    <p style="font-family:var(--mono);font-size:10px;color:var(--tx2);margin-bottom:10px">
      Chọn nhân vật (speaker ID), nhập văn bản tiếng Nhật, nhấn Phát để test.
    </p>
    <input class="spk-search" id="spk-search" placeholder="🔍 Tìm nhân vật... (vd: Zundamon, Metan)" oninput="filterSpeakers()">
    <div class="spk-list" id="spk-list"><div style="font-family:var(--mono);font-size:10px;color:var(--tx3);text-align:center;padding:20px">Đang tải...</div></div>
    <div style="display:flex;align-items:center;gap:8px;margin:10px 0 4px">
      <span style="font-family:var(--mono);font-size:10px;color:var(--tx2);white-space:nowrap">Speaker ID:</span>
      <input class="pinp" id="spk-id" type="number" min="0" step="1" value="0" style="width:70px">
      <span style="font-family:var(--mono);font-size:10px;color:var(--tx2);white-space:nowrap">Speed:</span>
      <input class="pinp" id="spk-speed" type="number" min="0.5" max="2.0" step="0.1" value="1.0" style="width:60px">
    </div>
    <textarea id="spk-text" style="width:100%;min-height:72px;background:var(--sf2);border:1px solid var(--bd2);color:var(--tx);padding:8px 10px;border-radius:8px;font-size:13px;outline:none;resize:vertical;margin-bottom:10px" placeholder="おはようございます！今日もよろしくね。"></textarea>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="bsv" onclick="playVoiceTest()" id="play-btn">▶ Phát thử</button>
      <button class="bsv" style="background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);color:var(--gn)" onclick="saveVoiceVoxDefault()" id="vv-save-btn" title="Lưu speaker ID này làm mặc định khi chat">💾 Lưu mặc định</button>
      <button class="bsv" style="background:var(--sf2);border:1px solid var(--bd2);color:var(--tx2)" onclick="loadSpeakers()">↺ Tải lại</button>
      <span id="vtest-status" style="font-family:var(--mono);font-size:10px;color:var(--tx3)"></span>
      <audio id="vtest-audio" style="display:none"></audio>
    </div>
  </div>
</div>

<!-- ═══ RESET AI ═════════════════════════════════════════════════════════════ -->
<div id="reset-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:110;align-items:center;justify-content:center">
  <div class="modal" style="width:min(420px,90vw)">
    <div class="mtitle">🔄 Reset AI
      <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 10px;cursor:pointer" onclick="closeResetAI()">✕</button>
    </div>
    <p style="font-family:var(--mono);font-size:11px;color:var(--tx2);line-height:1.7;margin-bottom:16px">
      Reset toàn bộ AI instance (PentaAI + VoiceVox + Valtec) và khởi tạo lại ngay lập tức.<br>
      Dùng sau khi nâng cấp module mà không muốn restart server hoàn toàn.<br>
      <span style="color:var(--am)">⚠️ Các kết nối WS đang mở không bị ngắt.</span>
    </p>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="bsv" style="background:var(--sf2);border:1px solid var(--bd2);color:var(--tx2)" onclick="closeResetAI()">Huỷ</button>
      <button class="bsv" style="background:var(--rd);border:none" onclick="doResetAI()" id="reset-btn">🔄 Xác nhận Reset</button>
    </div>
    <div id="reset-out" style="font-family:var(--mono);font-size:10px;color:var(--tx3);min-height:20px;margin-top:10px"></div>
  </div>
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
    <div class="mtitle">⚙️ Cài đặt Model & Cloud <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 10px;cursor:pointer" onclick="closeConfig()">✕</button></div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="font-size:11px;color:var(--tx2);font-weight:bold;margin-bottom:-4px">Ollama Local:</div>
      <input class="pinp" id="cfg-local-mod" type="text" placeholder="Local Model (vd: qwen2.5:1.5b)">
      <div style="font-size:11px;color:var(--tx2);font-weight:bold;margin-bottom:-4px;margin-top:8px">Cloud Fallback (OpenAI API Compat):</div>
      <input class="pinp" id="cfg-url" type="text" placeholder="URL API">
      <input class="pinp" id="cfg-key" type="password" placeholder="API Key">
      <input class="pinp" id="cfg-mod" type="text" placeholder="Cloud Model">
      <button class="bsv" style="margin-top:8px" onclick="saveConfig()">Lưu cài đặt</button>
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

<div id="gmail-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:102;align-items:center;justify-content:center">
  <div class="modal" style="width:min(520px,92vw)">
    <div class="mtitle">📧 Quản lý Gmail Notification <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 10px;cursor:pointer" onclick="closeGmailWhitelist()">✕</button></div>
    <div style="display:flex;flex-direction:column;gap:10px">
      <div style="font-size:10px;color:var(--tx2);font-weight:bold">Thêm email muốn nhận thông báo:</div>
      <div style="display:flex;gap:6px">
        <input class="pinp" id="gmail-email" type="text" placeholder="test.gmail" style="flex:1">
        <input class="pinp" id="gmail-nick" type="text" placeholder="test (nickname)" style="width:140px">
        <button class="bsv" style="padding:0 10px;white-space:nowrap" onclick="addGmailEntry()">Thêm</button>
      </div>
      <div style="font-size:10px;color:var(--tx2);font-weight:bold;margin-top:6px">Danh sách hiện tại:</div>
      <div id="gmail-wl-list" style="max-height:220px;overflow-y:auto;background:var(--sf2);border:1px solid var(--bd2);border-radius:8px;padding:8px;display:flex;flex-direction:column;gap:6px"></div>
      <button class="bsv" style="margin-top:8px" onclick="saveGmailConfig()">Lưu thay đổi</button>
    </div>
  </div>
</div>

<!-- ═══ HELP MODAL ════════════════════════════════════════════════════════════ -->
<div id="help-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:120;align-items:center;justify-content:center">
  <div class="help-modal">
    <div class="help-header">
      <span style="font-size:18px">📖</span>
      <span style="font-size:15px;font-weight:800">Hướng dẫn sử dụng PentaAI</span>
      <span id="help-ver" style="font-family:var(--mono);font-size:9px;color:var(--tx3);background:var(--sf2);border:1px solid var(--bd);padding:2px 8px;border-radius:4px"></span>
      <button style="margin-left:auto;background:none;border:1px solid var(--bd);color:var(--tx2);border-radius:4px;padding:3px 12px;cursor:pointer;font-size:12px" onclick="closeHelp()">✕</button>
    </div>
    <div class="help-body">
      <input class="help-search" id="help-search" placeholder="🔍 Tìm lệnh..." oninput="searchHelp(this.value)">
      <div class="help-tabs" id="help-tabs"></div>
      <div id="help-sections"></div>
      <div id="help-noresult" class="no-result" style="display:none">Không tìm thấy lệnh nào phù hợp</div>
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

async function _checkPcConfig() {
    // Kiểm tra pc_tailscale_ip và enable_penta_kuru_integration trong config
    try {
        const r = await fetch(`${BACKEND}/api/config_runtime`, {
            headers: {'Authorization': `Bearer ${getToken()}`}
        });
        const d = await r.json();
        if (!d.config) return null;
        const cfg = d.config;
        const tsIp = (cfg.pc_tailscale_ip || '').trim();
        const kuruOk = !!(cfg.enable_penta_kuru_integration && (cfg.penta_kuru_cloudflare_url || '').trim());
        return { tsIp, kuruOk, hasAnyConn: !!(tsIp || kuruOk) };
    } catch(e) { return null; }
}

async function toggleMode() {
    const isCmd = document.getElementById('mode-toggle').checked;
    currentMode = isCmd ? 'cmd' : 'chat';
    const lbl = document.getElementById('mode-lbl'), card = document.getElementById('mode-card'), btn = document.querySelector('.sndbtn'), inp = document.getElementById('inp');
    if (isCmd) {
        lbl.textContent = '⚡ ĐIỀU KHIỂN (CMD)'; lbl.style.color = 'var(--ac2)'; card.style.borderColor = 'var(--ac2)';
        btn.style.background = 'var(--ac2)'; inp.style.borderColor = 'var(--ac2)';
        appendSys('--- CHẾ ĐỘ ĐIỀU KHIỂN WINDOWS KÍCH HOẠT ---');
        // Kiểm tra cấu hình PC
        const pcCfg = await _checkPcConfig();
        if (pcCfg === null) {
            appendSys('⚠️ Không kiểm tra được config PC (server chưa sẵn sàng?)');
        } else if (!pcCfg.hasAnyConn) {
            appendSys('⚠️  PC CHƯA ĐƯỢC CẤU HÌNH! Lệnh sẽ không thực thi được.');
            appendSys('   → Mở ⚙ System → đặt "pc_tailscale_ip" = IP LAN/Tailscale của Windows');
            appendSys('   → Đặt "pc_auth_token" = auth_token trong PentaKuRu/data/server.json');
            appendSys('   → Nếu dùng Cloudflare: bật enable_penta_kuru_integration + penta_kuru_cloudflare_url');
        } else if (pcCfg.tsIp) {
            appendSys(`✅ Kết nối PC qua Tailscale/LAN: ${pcCfg.tsIp}`);
        } else if (pcCfg.kuruOk) {
            appendSys('✅ Kết nối PC qua Cloudflare Tunnel');
        }
        inp.placeholder = 'Nhập lệnh: "mở ghi chú", "tìm anime trên youtube", "tắt màn hình"...';
    } else {
        lbl.textContent = '💬 TRÒ CHUYỆN'; lbl.style.color = 'var(--ac)'; card.style.borderColor = 'var(--ac)';
        btn.style.background = 'var(--ac)'; inp.style.borderColor = 'var(--bd2)';
        inp.placeholder = 'Nhắn tin nà...';
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
            appendAI(d.text, d.ai_latency_ms, d.emotional_state, d.pipeline, d.mode_used, d.wiki_suggestions);
            if (d.emotional_state) setEmotion(d.emotional_state);
            if (d.hormone_levels) drawHormones(d.hormone_levels);
        } else if (d.type === 'audio_chunk') {
            playChunk(d.audio_b64, d.mime_type);
        } else if (d.type === 'error') {
            appendSys('\u26a0\ufe0f ' + d.msg);
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
function appendAI(t, ms, em, pipeline, modeUsed, wikiSuggestions) {
    const d = document.createElement('div'); d.className = 'msg ai';
    const meta = [
      `${ms || 0}ms`,
      em || '',
      modeUsed ? `mode:${modeUsed}` : '',
      pipeline ? `pipe:${pipeline}` : ''
    ].filter(Boolean).join(' \u00b7 ');
    let chipsHtml = '';
    // Chỉ hiển thị chip gợi ý khi phản hồi đến từ PentaWiki.
    if (pipeline === 'wiki_result' && Array.isArray(wikiSuggestions) && wikiSuggestions.length) {
        const chips = wikiSuggestions.map(kw =>
            `<button class="wiki-chip" onclick="sendWikiQuery(\`${kw.replace(/`/g,'\\`')}\`)">\uD83D\uDD0D ${kw}</button>`
        ).join('');
        chipsHtml = `<div class="wiki-chips">${chips}</div>`;
    }
    d.innerHTML = `<div class="av">AI</div><div class="mb"><div class="bbl">${t}</div>${chipsHtml}<div class="mm">${meta}</div></div>`;
    document.getElementById('msgs').appendChild(d); document.getElementById('msgs').scrollTop = 99999;
}
function sendWikiQuery(kw) {
    if (!wsOk) return;
    const ta = document.getElementById('inp');
    ta.value = kw;
    send();
}
function appendSys(t) {
    const d = document.createElement('div'); d.style = 'font-family:var(--mono);font-size:9px;color:var(--tx3);text-align:center;margin:10px 0';
    d.textContent = t; document.getElementById('msgs').appendChild(d); document.getElementById('msgs').scrollTop = 99999;
}

async function openConfig() { 
  document.getElementById('config-bg').style.display = 'flex'; 
  try {
    const res = await fetch(`${BACKEND}/api/config_cloud`, { headers: {'Authorization': `Bearer ${getToken()}`} });
    const d = await res.json();
    if(d.status === 'ok') {
      document.getElementById('cfg-url').value = d.url || '';
      document.getElementById('cfg-mod').value = d.model || '';
      document.getElementById('cfg-local-mod').value = d.local_model || '';
    }
  } catch(e) {}
}
function closeConfig() { document.getElementById('config-bg').style.display = 'none'; }
async function saveConfig() {
    const data = { 
        url: document.getElementById('cfg-url').value, 
        key: document.getElementById('cfg-key').value, 
        model: document.getElementById('cfg-mod').value,
        local_model: document.getElementById('cfg-local-mod').value
    };
    await fetch(`${BACKEND}/api/config_cloud`, { method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}`}, body: JSON.stringify(data) });
    closeConfig();
    appendSys('✅ Cấu hình Model AI đã được cập nhật');
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

// ─── Gmail Notification ────────────────────────────────────────────────────────
let _gmail_whitelist = [];

async function openGmailWhitelist() {
  document.getElementById('gmail-bg').style.display = 'flex';
  await loadGmailWhitelist();
}

function closeGmailWhitelist() { document.getElementById('gmail-bg').style.display = 'none'; }

async function loadGmailWhitelist() {
  try {
    const res = await fetch(`${BACKEND}/api/gmail_notify_whitelist`, {
      headers: {'Authorization': `Bearer ${getToken()}`}
    });
    const data = await res.json();
    _gmail_whitelist = data.whitelist || [];
    renderGmailList();
  } catch (e) {
    console.error('Load Gmail whitelist error:', e);
  }
}

function renderGmailList() {
  const cont = document.getElementById('gmail-wl-list');
  if (!_gmail_whitelist.length) {
    cont.innerHTML = '<div style="color:var(--tx3);font-size:9px">Chưa có email nào</div>';
    return;
  }
  cont.innerHTML = _gmail_whitelist.map(e => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px;background:var(--sf);border-radius:6px;border:1px solid var(--bd)">
      <div style="font-size:10px">
        <div style="color:var(--tx);font-weight:bold">${e.email}</div>
        <div style="color:var(--tx3);font-size:9px">👤 ${e.nickname}</div>
      </div>
      <button style="background:var(--rd);color:white;border:none;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:9px" onclick="removeGmailEntry('${e.email}')">Xóa</button>
    </div>
  `).join('');
}

async function addGmailEntry() {
  const email = document.getElementById('gmail-email').value.trim().toLowerCase();
  const nick = document.getElementById('gmail-nick').value.trim() || email.split('@')[0];
  
  if (!email) {
    alert('Email không được để trống');
    return;
  }
  
  if (_gmail_whitelist.some(e => e.email.toLowerCase() === email)) {
    alert('Email này đã có trong danh sách');
    return;
  }
  
  _gmail_whitelist.push({email, nickname: nick});
  renderGmailList();
  document.getElementById('gmail-email').value = '';
  document.getElementById('gmail-nick').value = '';
}

async function removeGmailEntry(email) {
  _gmail_whitelist = _gmail_whitelist.filter(e => e.email.toLowerCase() !== email.toLowerCase());
  renderGmailList();
}

async function saveGmailConfig() {
  try {
    const res = await fetch(`${BACKEND}/api/gmail_notify_whitelist`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`
      },
      body: JSON.stringify({action: 'set', whitelist: _gmail_whitelist})
    });
    const data = await res.json();
    if (data.status === 'ok') {
      closeGmailWhitelist();
      appendSys('✅ Gmail notification whitelist đã được lưu');
    } else {
      appendSys('⚠️ Lưu Gmail config lỗi');
    }
  } catch (e) {
    appendSys('⚠️ Lỗi khi lưu config: ' + e.message);
  }
}

async function toggleGmailNotif() {
  const enabled = document.getElementById('gmail-on').checked;
  try {
    const res = await fetch(`${BACKEND}/api/gmail_notify_enable`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`
      },
      body: JSON.stringify({enabled})
    });
    const data = await res.json();
    if (data.status === 'ok') {
      appendSys(enabled ? '✅ Gmail Notification bật' : '✅ Gmail Notification tắt');
    }
  } catch (e) {
    appendSys('⚠️ Lỗi: ' + e.message);
  }
}

document.getElementById('backend-url').value = BACKEND;
document.getElementById('inp').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
connect();
loadTtsDefaults();

// ═══ VOICEVOX VOICE TEST ═════════════════════════════════════════════════════

let _allSpeakers = [];
let _selectedSpkId = 0;

async function openVoiceTest() {
  document.getElementById('vtest-bg').style.display = 'flex';
  if (_allSpeakers.length === 0) await loadSpeakers();
}
function closeVoiceTest() { document.getElementById('vtest-bg').style.display = 'none'; }

async function loadSpeakers() {
  const list = document.getElementById('spk-list');
  list.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--tx3);text-align:center;padding:20px">Đang tải...</div>';
  try {
    const r = await fetch(`${BACKEND}/api/voicevox_speakers`, { headers: {'Authorization': `Bearer ${getToken()}`} });
    const d = await r.json();
    _allSpeakers = d.speakers || [];
    if (!_allSpeakers.length) {
      list.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--rd);text-align:center;padding:20px">⚠️ VoiceVox chưa sẵn sàng hoặc không có model</div>';
      return;
    }
    renderSpeakers(_allSpeakers);
  } catch(e) {
    list.innerHTML = `<div style="font-family:var(--mono);font-size:10px;color:var(--rd);text-align:center;padding:20px">⚠️ ${e.message}</div>`;
  }
}

function renderSpeakers(list) {
  const el = document.getElementById('spk-list');
  if (!list.length) { el.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--tx3);text-align:center;padding:12px">Không tìm thấy</div>'; return; }
  el.innerHTML = list.map(s =>
    `<div class="spk-item${s.id === _selectedSpkId ? ' sel' : ''}" onclick="selectSpk(${s.id})">
      <span class="sid">${s.id}</span>
      <span>${s.name}</span>
      <span style="color:var(--tx3);font-size:9px">– ${s.style}</span>
    </div>`
  ).join('');
}

function filterSpeakers() {
  const q = document.getElementById('spk-search').value.toLowerCase();
  renderSpeakers(_allSpeakers.filter(s =>
    s.name.toLowerCase().includes(q) || s.style.toLowerCase().includes(q) || String(s.id).includes(q)
  ));
}

function selectSpk(id) {
  _selectedSpkId = id;
  document.getElementById('spk-id').value = id;
  renderSpeakers(_allSpeakers.filter(s => {
    const q = document.getElementById('spk-search').value.toLowerCase();
    return !q || s.name.toLowerCase().includes(q) || String(s.id).includes(q);
  }));
}

async function playVoiceTest() {
  const text = document.getElementById('spk-text').value.trim();
  if (!text) { document.getElementById('vtest-status').textContent = '⚠️ Nhập văn bản trước'; return; }
  const spkId = parseInt(document.getElementById('spk-id').value) || 0;
  const speed  = parseFloat(document.getElementById('spk-speed').value) || 1.0;
  const btn = document.getElementById('play-btn');
  const st = document.getElementById('vtest-status');
  btn.disabled = true; st.textContent = '⏳ Đang tổng hợp...';
  try {
    const r = await fetch(`${BACKEND}/api/tts_test`, {
      method: 'POST',
      headers: {'Content-Type':'application/json','Authorization':`Bearer ${getToken()}`},
      body: JSON.stringify({ text, speaker_id: spkId, speed })
    });
    if (!r.ok) { const e = await r.json(); st.textContent = '⚠️ ' + (e.error || r.status); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = document.getElementById('vtest-audio');
    audio.src = url;
    audio.onended = () => { URL.revokeObjectURL(url); st.textContent = '✅ Xong'; };
    await audio.play();
    st.textContent = `▶ Đang phát (ID ${spkId})`;
  } catch(e) {
    st.textContent = '⚠️ ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ═══ LƯU MẶC ĐỊNH TTS ═══════════════════════════════════════════════════════

async function saveVoiceVoxDefault() {
  const spkId = parseInt(document.getElementById('spk-id').value) || 0;
  const btn = document.getElementById('vv-save-btn');
  const st = document.getElementById('vtest-status');
  btn.disabled = true;
  try {
    const r = await fetch(`${BACKEND}/api/config`, {
      method: 'POST',
      headers: {'Content-Type':'application/json','Authorization':`Bearer ${getToken()}`},
      body: JSON.stringify({ voicevox_speaker_id: spkId })
    });
    const d = await r.json();
    if (d.status === 'ok') {
      st.style.color = 'var(--gn)';
      st.textContent = `✅ Đã lưu ID ${spkId} làm mặc định`;
      setTimeout(() => { if (st.textContent.startsWith('✅ Đã lưu ID')) st.textContent = ''; }, 3000);
    } else { st.style.color = 'var(--rd)'; st.textContent = '⚠️ Lưu thất bại'; }
  } catch(e) { st.style.color = 'var(--rd)'; st.textContent = '⚠️ ' + e.message; }
  finally { btn.disabled = false; }
}

async function saveValtecDefault() {
  const spk = document.getElementById('valtec-spk').value;
  const spd = parseFloat(document.getElementById('valtec-spd').value) || 1.0;
  const st = document.getElementById('valtec-save-st');
  try {
    const r = await fetch(`${BACKEND}/api/config`, {
      method: 'POST',
      headers: {'Content-Type':'application/json','Authorization':`Bearer ${getToken()}`},
      body: JSON.stringify({ chat_speaker: spk, chat_speed: spd,
                             proactive_vi_speaker: spk, proactive_vi_speed: spd })
    });
    const d = await r.json();
    if (d.status === 'ok') {
      st.style.color = 'var(--gn)';
      st.textContent = `✅ Đã lưu ${spk} tốc độ ${spd}`;
      setTimeout(() => { st.textContent = ''; }, 3000);
    } else { st.style.color = 'var(--rd)'; st.textContent = '⚠️ Lưu thất bại'; }
  } catch(e) { st.style.color = 'var(--rd)'; st.textContent = '⚠️ ' + e.message; }
}

async function loadTtsDefaults() {
  try {
    const r = await fetch(`${BACKEND}/api/config_runtime`, { headers: {'Authorization':`Bearer ${getToken()}`} });
    const d = await r.json();
    if (!d.config) return;
    const spkEl = document.getElementById('valtec-spk');
    const spdEl = document.getElementById('valtec-spd');
    if (d.config.chat_speaker && spkEl) spkEl.value = d.config.chat_speaker;
    if (d.config.chat_speed   && spdEl) spdEl.value = d.config.chat_speed;
  } catch(_) {}
}

// ═══ RESET AI ════════════════════════════════════════════════════════════════

function openResetAI() {
  document.getElementById('reset-bg').style.display = 'flex';
  document.getElementById('reset-out').textContent = '';
}
function closeResetAI() { document.getElementById('reset-bg').style.display = 'none'; }

async function doResetAI() {
  const btn = document.getElementById('reset-btn');
  const out = document.getElementById('reset-out');
  btn.disabled = true; out.textContent = '⏳ Đang reset...';
  try {
    const r = await fetch(`${BACKEND}/admin/reset_ai`, {
      method: 'POST',
      headers: {'Authorization': `Bearer ${getToken()}`}
    });
    const d = await r.json();
    if (d.ok) {
      out.style.color = 'var(--gn)';
      out.textContent = '✅ ' + d.message;
      appendSys('✅ AI đã được reset và khởi tạo lại thành công');
      refreshHealth();
      setTimeout(closeResetAI, 1800);
    } else {
      out.style.color = 'var(--rd)';
      out.textContent = '⚠️ ' + (d.error || 'Thất bại');
    }
  } catch(e) {
    out.style.color = 'var(--rd)';
    out.textContent = '⚠️ ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

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
// ═══ HELP MODAL ══════════════════════════════════════════════════════════════

let _helpData = null;

async function openHelp() {
  document.getElementById('help-bg').style.display = 'flex';
  if (_helpData) return;
  try {
    const r = await fetch('/help.json');
    _helpData = await r.json();
    renderHelp(_helpData);
  } catch(e) {
    document.getElementById('help-sections').innerHTML =
      `<div class="no-result">⚠️ Không tải được help.json: ${e.message}</div>`;
  }
}

function closeHelp() { document.getElementById('help-bg').style.display = 'none'; }

function renderHelp(data) {
  document.getElementById('help-ver').textContent = 'v' + (data.version || '?');
  const tabsEl = document.getElementById('help-tabs');
  const secsEl = document.getElementById('help-sections');
  tabsEl.innerHTML = '';
  secsEl.innerHTML = '';

  data.sections.forEach((sec, i) => {
    const tab = document.createElement('button');
    tab.className = 'htab' + (i === 0 ? ' active' : '');
    tab.innerHTML = `${sec.icon} ${sec.title}`;
    tab.onclick = () => switchHelpTab(sec.id);
    tabsEl.appendChild(tab);

    const secDiv = document.createElement('div');
    secDiv.className = 'help-section' + (i === 0 ? ' active' : '');
    secDiv.id = 'hsec-' + sec.id;
    secDiv.innerHTML = `
      <div class="help-section-title">
        <span style="font-size:18px">${sec.icon}</span>
        <span style="color:${sec.color}">${sec.title}</span>
      </div>
      ${sec.commands.map(c => `
        <div class="help-row">
          <span class="hcmd" style="border-color:${sec.color}33;color:${sec.color}">${c.cmd}</span>
          <span class="hdesc">${c.desc}</span>
        </div>`).join('')}`;
    secsEl.appendChild(secDiv);
  });
}

function switchHelpTab(id) {
  document.querySelectorAll('.htab').forEach(t =>
    t.classList.toggle('active', t.textContent.trim().includes(
      (_helpData.sections.find(s => s.id === id) || {}).title || ''
    ))
  );
  document.querySelectorAll('.help-section').forEach(s =>
    s.classList.toggle('active', s.id === 'hsec-' + id)
  );
  document.getElementById('help-search').value = '';
  document.getElementById('help-noresult').style.display = 'none';
}

function searchHelp(q) {
  if (!_helpData) return;
  const qlow = q.trim().toLowerCase();
  if (!qlow) {
    renderHelp(_helpData);
    return;
  }
  const tabsEl = document.getElementById('help-tabs');
  const secsEl = document.getElementById('help-sections');
  tabsEl.innerHTML = '<button class="htab active">🔍 Kết quả tìm kiếm</button>';
  secsEl.innerHTML = '';
  let results = [];
  _helpData.sections.forEach(sec => {
    sec.commands.forEach(c => {
      if (c.cmd.toLowerCase().includes(qlow) || c.desc.toLowerCase().includes(qlow)) {
        results.push({ ...c, _color: sec.color, _icon: sec.icon, _section: sec.title });
      }
    });
  });
  if (!results.length) {
    secsEl.innerHTML = '';
    document.getElementById('help-noresult').style.display = 'block';
    return;
  }
  document.getElementById('help-noresult').style.display = 'none';
  const div = document.createElement('div');
  div.className = 'help-section active';
  div.innerHTML = results.map(c => `
    <div class="help-row">
      <div>
        <span class="hcmd" style="border-color:${c._color}33;color:${c._color}">${c.cmd}</span>
        <div style="font-family:var(--mono);font-size:9px;color:var(--tx3);margin-top:3px">${c._icon} ${c._section}</div>
      </div>
      <span class="hdesc">${c.desc}</span>
    </div>`).join('');
  secsEl.appendChild(div);
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeHelp(); closeControl(); closeConfig(); closeRuntimeConfig(); closeGmailWhitelist(); } });

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
</body>
</html>
"""

@app.get("/help.json")
async def get_help():
    root_dir = os.path.dirname(__file__)
    help_path = os.path.join(root_dir, "data", "help.json")
    try:
        with open(help_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    except FileNotFoundError:
        # Fallback for legacy location.
        legacy_path = os.path.join(root_dir, "help.json")
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                return JSONResponse(content=json.load(f))
        except FileNotFoundError:
            return JSONResponse(content={"error": "help.json not found"}, status_code=404)

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

if __name__ == "__main__":
    import uvicorn
    log.info(f"🚀 PentaAI UI Client đang chạy tại http://0.0.0.0:{UI_PORT}")
    log.info(f"🔗 Đang trỏ về Backend: http://localhost:{AI_SERVER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
