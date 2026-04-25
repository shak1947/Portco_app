"""
app.py — Portfolio Analysis Agent Web UI
Run: py app.py
Open: http://localhost:5000
"""

import json
import logging
import os
import queue
import threading
import time

import litellm
from datetime import datetime
from flask import Flask, render_template_string, request, Response, jsonify
from dotenv import load_dotenv
from database import execute_query, get_schema, seed_sample_data, engine
from tools import TOOL_DEFINITIONS, execute_tool
from prompts import SYSTEM_PROMPT
from sqlalchemy import text

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
MODEL = os.getenv("MODEL", "anthropic/claude-sonnet-4-6")
litellm.set_verbose = False

def _log_env_status():
    env_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]
    status = {key: bool(os.getenv(key)) for key in env_keys}
    logger.info("Litellm startup check: MODEL=%s, env_keys=%s", MODEL, status)


_log_env_status()


def _serialize_tool_call(tool_call):
    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", None),
        "type": getattr(tool_call, "type", "function"),
        "function": {
            "name": getattr(function, "name", None),
            "arguments": getattr(function, "arguments", "") if function is not None else "",
        },
    }


def _parse_tool_args(tool_call):
    function = getattr(tool_call, "function", None)
    if function is None:
        return {}
    raw_args = getattr(function, "arguments", "")
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str):
        return {}
    try:
        return json.loads(raw_args)
    except json.JSONDecodeError:
        return {}


# ── Agent runner ───────────────────────────────────────────────────────────────
def run_agent_streaming(user_question: str, response_queue: queue.Queue):
    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": user_question},
    ]
    response_queue.put({"type": "status", "msg": f"Thinking..."})

    for iteration in range(12):
        try:
            response = litellm.completion(
                model=MODEL, messages=messages,
                tools=TOOL_DEFINITIONS, tool_choice="auto", max_tokens=4096)
        except Exception as e:
            response_queue.put({"type": "error", "msg": str(e)})
            return

        message = response.choices[0].message
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [_serialize_tool_call(tc) for tc in message.tool_calls],
        })

        if not message.tool_calls:
            response_queue.put({"type": "answer", "msg": message.content or ""})
            return

        for tc in message.tool_calls:
            name = tc.function.name
            args = _parse_tool_args(tc)
            logger.info(
                "Received tool call: name=%s id=%s args=%s",
                name,
                getattr(tc, "id", None),
                getattr(getattr(tc, "function", None), "arguments", None),
            )

            response_queue.put({"type": "tool_start", "tool": name,
                                 "detail": args.get("rationale") or args.get("sql","")[:80]})

            result = execute_tool(name, args)

            # If it's a query result, send the data for table rendering
            if name == "execute_sql_query":
                try:
                    parsed = json.loads(result)
                    if parsed.get("success") and parsed.get("rows"):
                        response_queue.put({"type": "table",
                                            "columns": parsed["columns"],
                                            "rows":    parsed["rows"][:50],
                                            "count":   parsed["row_count"]})
                except:
                    pass

            response_queue.put({"type": "tool_done", "tool": name,
                                 "rows": json.loads(result).get("row_count","") if name=="execute_sql_query" else ""})

            messages.append({"role":"tool","tool_call_id":tc.id,"name":name,"content":result})

    response_queue.put({"type":"error","msg":"Max iterations reached."})


# ── Data helpers ───────────────────────────────────────────────────────────────
def get_portfolio_summary():
    q = execute_query("""
        SELECT c.name, c.sector, qf.revenue_mm, qf.ebitda_mm, qf.ebitda_margin, qf.yoy_growth
        FROM companies c
        JOIN quarterly_financials qf ON c.id = qf.company_id
        WHERE qf.period = '2024-Q4'
        ORDER BY qf.ebitda_margin DESC
    """)
    return q

def get_comps_summary():
    q = execute_query("""
        SELECT ticker, name, sector_key, market_cap_mm, ev_ebitda, ebitda_margin, revenue_growth, last_updated
        FROM market_comps
        ORDER BY sector_key, market_cap_mm DESC NULLS LAST
        LIMIT 50
    """)
    return q

def get_comp_count():
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM market_comps")).scalar()
    except:
        return 0

def get_price_history(ticker):
    q = execute_query(f"""
        SELECT date, close FROM comp_price_history
        WHERE ticker = '{ticker}'
        ORDER BY date ASC
    """)
    return q


# ── HTML ───────────────────────────────────────────────────────────────────────
HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PE Portfolio Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js"></script>
<style>
:root {
  --navy:  #0A1628;
  --navy2: #0F1F3D;
  --blue:  #1E6FD9;
  --teal:  #0ABFBC;
  --gold:  #F5A623;
  --green: #27AE60;
  --red:   #E74C3C;
  --grey1: #F8F9FC;
  --grey2: #EEF0F5;
  --grey3: #B0B8CC;
  --text:  #1A1F36;
  --white: #FFFFFF;
  --sidebar-w: 260px;
  --header-h:  58px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Sora", sans-serif; background: var(--grey1); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* Header */
.header { height: var(--header-h); background: var(--navy); display: flex; align-items: center; padding: 0 20px; gap: 16px; border-bottom: 2px solid var(--gold); flex-shrink: 0; z-index: 50; }
.header-logo { width: 32px; height: 32px; background: var(--gold); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.header-title { font-size: 16px; font-weight: 700; color: white; letter-spacing: -0.3px; }
.header-sub { font-size: 10px; color: var(--grey3); letter-spacing: 1px; text-transform: uppercase; }
.header-spacer { flex: 1; }
.header-model { font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--teal); background: rgba(10,191,188,0.1); border: 1px solid rgba(10,191,188,0.3); padding: 4px 10px; border-radius: 20px; }
.header-tabs { display: flex; gap: 4px; }
.tab-btn { padding: 6px 16px; border: none; border-radius: 8px; font-family: "Sora", sans-serif; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s; background: rgba(255,255,255,0.07); color: var(--grey3); }
.tab-btn.active { background: var(--blue); color: white; }

/* Layout */
.main { display: flex; flex: 1; overflow: hidden; }

/* Sidebar */
.sidebar { width: var(--sidebar-w); background: var(--navy2); border-right: 1px solid rgba(255,255,255,0.06); display: flex; flex-direction: column; flex-shrink: 0; overflow: hidden; }
.sidebar-section { padding: 14px 16px 8px; font-size: 10px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase; color: var(--grey3); }
.sidebar-item { padding: 8px 16px; font-size: 12px; color: rgba(255,255,255,0.7); cursor: pointer; display: flex; align-items: center; gap: 8px; transition: all 0.15s; border-left: 3px solid transparent; }
.sidebar-item:hover { background: rgba(255,255,255,0.05); color: white; }
.sidebar-item.active { background: rgba(30,111,217,0.15); color: var(--teal); border-left-color: var(--teal); }
.sidebar-item .sector-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sidebar-item .margin-pill { margin-left: auto; font-family: "JetBrains Mono", monospace; font-size: 10px; color: var(--teal); }
.sidebar-divider { height: 1px; background: rgba(255,255,255,0.06); margin: 8px 0; }
.comp-count { padding: 8px 16px; font-size: 11px; color: var(--grey3); }
.refresh-btn { margin: 8px 16px; padding: 8px 12px; background: rgba(245,166,35,0.1); border: 1px solid rgba(245,166,35,0.3); color: var(--gold); border-radius: 8px; font-family: "Sora",sans-serif; font-size: 11px; font-weight: 500; cursor: pointer; text-align: center; transition: all 0.2s; }
.refresh-btn:hover { background: rgba(245,166,35,0.2); }

/* Content panels */
.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.panel { flex: 1; overflow: hidden; display: none; flex-direction: column; }
.panel.active { display: flex; }

/* Chat panel */
.chat-messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.chat-empty { text-align: center; margin: auto; color: var(--grey3); }
.chat-empty-icon { font-size: 48px; margin-bottom: 16px; }
.chat-empty-title { font-size: 18px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.chat-empty-sub { font-size: 13px; line-height: 1.6; max-width: 380px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 20px; }
.suggestion { padding: 8px 14px; background: white; border: 1.5px solid var(--grey2); border-radius: 20px; font-size: 12px; color: var(--text); cursor: pointer; transition: all 0.2s; }
.suggestion:hover { border-color: var(--blue); color: var(--blue); background: rgba(30,111,217,0.04); }

.msg { display: flex; flex-direction: column; gap: 4px; max-width: 820px; }
.msg.user { align-self: flex-end; align-items: flex-end; }
.msg.agent { align-self: flex-start; }
.msg-label { font-size: 10px; font-weight: 600; letter-spacing: 0.8px; text-transform: uppercase; color: var(--grey3); padding: 0 4px; }
.msg-bubble { padding: 14px 18px; border-radius: 16px; font-size: 13.5px; line-height: 1.7; }
.msg.user .msg-bubble { background: var(--blue); color: white; border-bottom-right-radius: 4px; }
.msg.agent .msg-bubble { background: white; color: var(--text); border-bottom-left-radius: 4px; box-shadow: 0 1px 8px rgba(0,0,0,0.06); }
.msg.agent .msg-bubble h2 { font-size: 15px; font-weight: 700; margin: 12px 0 6px; color: var(--navy); }
.msg.agent .msg-bubble h3 { font-size: 13px; font-weight: 600; margin: 10px 0 4px; color: var(--navy); }
.msg.agent .msg-bubble p { margin: 6px 0; }
.msg.agent .msg-bubble ul, .msg.agent .msg-bubble ol { padding-left: 18px; margin: 6px 0; }
.msg.agent .msg-bubble li { margin: 3px 0; }
.msg.agent .msg-bubble strong { color: var(--navy); }
.msg.agent .msg-bubble table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 10px 0; }
.msg.agent .msg-bubble th { background: var(--navy); color: white; padding: 7px 12px; text-align: left; font-weight: 600; }
.msg.agent .msg-bubble td { padding: 6px 12px; border-bottom: 1px solid var(--grey2); }
.msg.agent .msg-bubble tr:hover td { background: var(--grey1); }
.msg.agent .msg-bubble code { font-family: "JetBrains Mono", monospace; font-size: 11px; background: var(--grey2); padding: 1px 5px; border-radius: 4px; }

.tool-trace { background: var(--grey1); border: 1px solid var(--grey2); border-radius: 10px; padding: 10px 14px; margin: 4px 0; font-size: 11px; }
.tool-trace-row { display: flex; align-items: center; gap: 8px; color: var(--grey3); }
.tool-trace-row .tool-name { color: var(--teal); font-family: "JetBrains Mono", monospace; font-weight: 500; }
.tool-trace-row .tool-detail { color: var(--text); opacity: 0.6; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-spinner { width: 12px; height: 12px; border: 2px solid var(--grey2); border-top-color: var(--teal); border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0; }
.tool-done-icon { color: var(--green); font-size: 12px; }

.data-table-wrap { overflow-x: auto; margin: 8px 0; border-radius: 8px; border: 1px solid var(--grey2); }
.data-table { border-collapse: collapse; font-size: 12px; width: 100%; }
.data-table th { background: var(--navy); color: white; padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; white-space: nowrap; }
.data-table td { padding: 6px 12px; border-bottom: 1px solid var(--grey2); white-space: nowrap; }
.data-table tr:hover td { background: rgba(30,111,217,0.04); }
.data-table-count { font-size: 11px; color: var(--grey3); margin-top: 4px; padding: 0 4px; }

/* Thinking dots */
.thinking { display: flex; gap: 5px; align-items: center; padding: 14px 18px; background: white; border-radius: 16px; border-bottom-left-radius: 4px; box-shadow: 0 1px 8px rgba(0,0,0,0.06); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--blue); animation: bounce 1.2s ease-in-out infinite; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

/* Chat input */
.chat-input-wrap { padding: 16px 20px; background: white; border-top: 1px solid var(--grey2); display: flex; gap: 10px; align-items: flex-end; }
.chat-input { flex: 1; padding: 12px 16px; border: 1.5px solid var(--grey2); border-radius: 12px; font-family: "Sora", sans-serif; font-size: 13px; color: var(--text); resize: none; max-height: 120px; min-height: 48px; transition: border-color 0.2s; line-height: 1.5; }
.chat-input:focus { outline: none; border-color: var(--blue); }
.send-btn { width: 44px; height: 44px; background: var(--blue); border: none; border-radius: 12px; cursor: pointer; color: white; font-size: 18px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all 0.2s; }
.send-btn:hover { background: #1559B5; transform: translateY(-1px); }
.send-btn:disabled { background: var(--grey3); cursor: not-allowed; transform: none; }

/* Comps panel */
.comps-header { padding: 20px 24px 0; display: flex; align-items: center; justify-content: space-between; }
.comps-title { font-size: 18px; font-weight: 700; color: var(--navy); }
.comps-sub { font-size: 12px; color: var(--grey3); margin-top: 2px; }
.fetch-comps-btn { padding: 10px 20px; background: var(--navy); color: white; border: none; border-radius: 10px; font-family: "Sora",sans-serif; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: all 0.2s; }
.fetch-comps-btn:hover { background: var(--blue); }
.fetch-comps-btn:disabled { background: var(--grey3); cursor: not-allowed; }
.comps-table-wrap { flex: 1; overflow: auto; padding: 20px 24px; }
.comps-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.comps-table th { background: var(--navy); color: white; padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; position: sticky; top: 0; z-index: 1; }
.comps-table td { padding: 9px 14px; border-bottom: 1px solid var(--grey2); }
.comps-table tr:hover td { background: rgba(30,111,217,0.03); }
.comps-table .sector-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; background: rgba(10,191,188,0.1); color: var(--teal); }
.comps-table .num { font-family: "JetBrains Mono", monospace; font-size: 12px; text-align: right; }
.comps-table .positive { color: var(--green); }
.comps-table .negative { color: var(--red); }
.comps-empty { text-align: center; padding: 60px; color: var(--grey3); }
.fetch-log { background: var(--navy); color: #90CAF9; font-family: "JetBrains Mono", monospace; font-size: 11px; padding: 12px 16px; border-radius: 10px; max-height: 180px; overflow-y: auto; margin: 0 24px 16px; display: none; line-height: 1.8; }
.fetch-log.show { display: block; }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes bounce { 0%,80%,100%{transform:scale(0.6)}40%{transform:scale(1)} }
</style>
</head>
<body>

<div class="header">
  <div class="header-logo">📊</div>
  <div>
    <div class="header-title">PE Portfolio Intelligence</div>
    <div class="header-sub">AI-Powered Financial Analysis</div>
  </div>
  <div class="header-spacer"></div>
  <div class="header-tabs">
    <button class="tab-btn active" onclick="switchTab('chat')">💬 Chat</button>
    <button class="tab-btn" onclick="switchTab('comps')">📈 Market Comps</button>
  </div>
  <div class="header-model" id="modelBadge">Loading...</div>
</div>

<div class="main">

  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-section">Portfolio Companies</div>
    <div id="companyList">
      <div style="padding:20px;color:var(--grey3);font-size:12px">Loading...</div>
    </div>
    <div class="sidebar-divider"></div>
    <div class="sidebar-section">Public Comps</div>
    <div class="comp-count" id="compCount">Loading...</div>
    <button class="refresh-btn" onclick="triggerFetchComps()">⟳ Refresh Market Data</button>
  </div>

  <!-- Content -->
  <div class="content">

    <!-- Chat panel -->
    <div class="panel active" id="panel-chat">
      <div class="chat-messages" id="chatMessages">
        <div class="chat-empty">
          <div class="chat-empty-icon">🔍</div>
          <div class="chat-empty-title">Ask anything about your portfolio</div>
          <div class="chat-empty-sub">The agent queries your live Supabase database and public market data to answer your questions.</div>
          <div class="suggestions">
            <div class="suggestion" onclick="sendSuggestion(this)">Which company has the highest EBITDA margin?</div>
            <div class="suggestion" onclick="sendSuggestion(this)">Revenue trend across all companies 2023-2024</div>
            <div class="suggestion" onclick="sendSuggestion(this)">Compare portfolio EBITDA vs public peer medians</div>
            <div class="suggestion" onclick="sendSuggestion(this)">Which sector has the strongest YoY growth?</div>
            <div class="suggestion" onclick="sendSuggestion(this)">Show me the bottom 3 companies by margin</div>
            <div class="suggestion" onclick="sendSuggestion(this)">Permian Energy vs public energy comps</div>
          </div>
        </div>
      </div>
      <div class="chat-input-wrap">
        <textarea class="chat-input" id="chatInput" placeholder="Ask about your portfolio companies, trends, comparables..." rows="1"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage()}"
          oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'"></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendMessage()">↑</button>
      </div>
    </div>

    <!-- Comps panel -->
    <div class="panel" id="panel-comps">
      <div class="comps-header">
        <div>
          <div class="comps-title">Public Market Comparables</div>
          <div class="comps-sub" id="compsLastUpdated">Live data from Yahoo Finance</div>
        </div>
        <button class="fetch-comps-btn" id="fetchCompsBtn" onclick="triggerFetchComps()">
          <span>⟳</span> <span id="fetchBtnText">Fetch 5-Year Data</span>
        </button>
      </div>
      <div class="fetch-log" id="fetchLog"></div>
      <div class="comps-table-wrap" id="compsTableWrap">
        <div class="comps-empty">No comp data yet. Click "Fetch 5-Year Data" to pull from Yahoo Finance.</div>
      </div>
    </div>

  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let isAgentRunning = false;
let currentThinkingEl = null;

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadModel();
  loadSidebar();
  loadCompsTable();
});

function loadModel() {
  fetch("/api/model").then(r=>r.json()).then(d=>{
    document.getElementById("modelBadge").textContent = d.model;
  });
}

function loadSidebar() {
  fetch("/api/portfolio").then(r=>r.json()).then(d=>{
    const list = document.getElementById("companyList");
    if (!d.rows || d.rows.length === 0) {
      list.innerHTML = '<div style="padding:16px;font-size:12px;color:var(--grey3)">No data</div>';
      return;
    }
    const SECTOR_COLORS = {
      "Healthcare":"#E74C3C","Construction":"#E67E22","Technology":"#3498DB",
      "Retail":"#9B59B6","Industrial":"#2ECC71","Consumer":"#F39C12",
      "Logistics":"#1ABC9C","Energy":"#F1C40F"
    };
    list.innerHTML = d.rows.map(row => {
      const [name, sector, rev, ebitda, margin] = row;
      const color = SECTOR_COLORS[sector] || "#95A5A6";
      const pct = margin ? (margin*100).toFixed(1)+"%" : "—";
      const short = name.replace(" Inc.","").replace(" Holdings","")
                        .replace(" Services","").replace(" Manufacturing","")
                        .replace(" Platform","");
      return `<div class="sidebar-item" onclick="askAbout('${name}')">
        <div class="sector-dot" style="background:${color}"></div>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${short}</span>
        <span class="margin-pill">${pct}</span>
      </div>`;
    }).join("");

    // Comp count
    fetch("/api/comp_count").then(r=>r.json()).then(c=>{
      document.getElementById("compCount").textContent =
        c.count > 0 ? `${c.count} tickers stored` : "No data fetched yet";
    });
  });
}

function loadCompsTable() {
  fetch("/api/comps").then(r=>r.json()).then(d=>{
    const wrap = document.getElementById("compsTableWrap");
    if (!d.rows || d.rows.length === 0) {
      wrap.innerHTML = '<div class="comps-empty">No comp data yet. Click "Fetch 5-Year Data" to pull from Yahoo Finance.</div>';
      return;
    }
    const cols = d.columns;
    let html = `<table class="comps-table"><thead><tr>${cols.map(c=>`<th>${c.toUpperCase().replace("_"," ")}</th>`).join("")}</tr></thead><tbody>`;
    d.rows.forEach(row => {
      html += "<tr>" + row.map((v,i) => {
        const col = cols[i];
        if (col === "sector_key") return `<td><span class="sector-badge">${v||"—"}</span></td>`;
        if (col === "last_updated") return `<td style="font-size:10px;color:var(--grey3)">${v ? v.substring(0,10) : "—"}</td>`;
        if (v === null || v === "None" || v === "") return `<td style="color:var(--grey3)">—</td>`;
        if (col.includes("margin") || col.includes("growth")) {
          const n = parseFloat(v);
          const cls = n >= 0 ? "positive" : "negative";
          return `<td class="num ${cls}">${isNaN(n) ? v : (n*100).toFixed(1)+"%"}</td>`;
        }
        if (col.includes("ev_")) return `<td class="num">${parseFloat(v).toFixed(1)}x</td>`;
        if (col.includes("mm")) return `<td class="num">$${parseFloat(v).toFixed(0)}M</td>`;
        return `<td>${v}</td>`;
      }).join("") + "</tr>";
    });
    html += "</tbody></table>";
    wrap.innerHTML = html;
    if (d.rows[0]) {
      const lastUp = d.rows[0][7] || "";
      document.getElementById("compsLastUpdated").textContent =
        lastUp ? `Last updated: ${lastUp.substring(0,16)}` : "Yahoo Finance data";
    }
  });
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`panel-${tab}`).classList.add("active");
  event.target.classList.add("active");
  if (tab === "comps") loadCompsTable();
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function sendSuggestion(el) {
  document.getElementById("chatInput").value = el.textContent;
  sendMessage();
}

function askAbout(name) {
  document.getElementById("chatInput").value = `Give me a full performance summary for ${name}`;
  switchTab("chat");
  document.querySelectorAll(".tab-btn")[0].classList.add("active");
  document.querySelectorAll(".tab-btn")[1].classList.remove("active");
  sendMessage();
}

function sendMessage() {
  const input = document.getElementById("chatInput");
  const question = input.value.trim();
  if (!question || isAgentRunning) return;

  // Clear empty state
  const emptyEl = document.querySelector(".chat-empty");
  if (emptyEl) emptyEl.remove();

  appendMsg("user", question);
  input.value = "";
  input.style.height = "auto";

  const thinkingEl = appendThinking();
  currentThinkingEl = thinkingEl;
  isAgentRunning = true;
  document.getElementById("sendBtn").disabled = true;

  const es = new EventSource(`/api/ask?q=${encodeURIComponent(question)}`);
  let toolTraceEl = null;

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === "tool_start") {
      if (thinkingEl && thinkingEl.parentNode) thinkingEl.remove();
      toolTraceEl = appendToolTrace(data.tool, data.detail, true);
    }
    else if (data.type === "tool_done") {
      if (toolTraceEl) updateToolTrace(toolTraceEl, data.rows);
      toolTraceEl = null;
    }
    else if (data.type === "table") {
      appendDataTable(data.columns, data.rows, data.count);
    }
    else if (data.type === "answer") {
      if (thinkingEl && thinkingEl.parentNode) thinkingEl.remove();
      appendMsg("agent", data.msg);
      es.close();
      isAgentRunning = false;
      document.getElementById("sendBtn").disabled = false;
    }
    else if (data.type === "error") {
      if (thinkingEl && thinkingEl.parentNode) thinkingEl.remove();
      appendMsg("agent", `**Error:** ${data.msg}`);
      es.close();
      isAgentRunning = false;
      document.getElementById("sendBtn").disabled = false;
    }
  };

  es.onerror = () => {
    if (thinkingEl && thinkingEl.parentNode) thinkingEl.remove();
    es.close();
    isAgentRunning = false;
    document.getElementById("sendBtn").disabled = false;
  };
}

function appendMsg(role, text) {
  const msgs = document.getElementById("chatMessages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (role === "agent") {
    div.innerHTML = `<div class="msg-label">Agent</div>
      <div class="msg-bubble">${marked.parse(text)}</div>`;
  } else {
    div.innerHTML = `<div class="msg-label">You</div>
      <div class="msg-bubble">${escHtml(text)}</div>`;
  }
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function appendThinking() {
  const msgs = document.getElementById("chatMessages");
  const div = document.createElement("div");
  div.className = "msg agent";
  div.innerHTML = `<div class="msg-label">Agent</div>
    <div class="thinking"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function appendToolTrace(toolName, detail, running) {
  const msgs = document.getElementById("chatMessages");
  const div = document.createElement("div");
  div.className = "tool-trace";
  div.innerHTML = `<div class="tool-trace-row">
    ${running ? '<div class="tool-spinner"></div>' : '<span class="tool-done-icon">✓</span>'}
    <span class="tool-name">${toolName}</span>
    <span class="tool-detail">${escHtml(detail||"")}</span>
  </div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function updateToolTrace(el, rows) {
  const row = el.querySelector(".tool-trace-row");
  if (!row) return;
  const spinner = row.querySelector(".tool-spinner");
  if (spinner) { const done = document.createElement("span"); done.className="tool-done-icon"; done.textContent="✓"; spinner.replaceWith(done); }
  if (rows) { const detail = row.querySelector(".tool-detail"); if (detail) detail.textContent += ` → ${rows} rows`; }
}

function appendDataTable(columns, rows, count) {
  const msgs = document.getElementById("chatMessages");
  const wrap = document.createElement("div");
  wrap.className = "data-table-wrap";
  let html = `<table class="data-table"><thead><tr>${columns.map(c=>`<th>${c}</th>`).join("")}</tr></thead><tbody>`;
  rows.forEach(row => {
    html += "<tr>" + row.map(v => `<td>${v === null ? "—" : v}</td>`).join("") + "</tr>";
  });
  html += "</tbody></table>";
  if (count > rows.length) html += `<div class="data-table-count">Showing ${rows.length} of ${count} rows</div>`;
  wrap.innerHTML = html;
  msgs.appendChild(wrap);
  msgs.scrollTop = msgs.scrollHeight;
}

// ── Comps fetch ───────────────────────────────────────────────────────────────
function triggerFetchComps() {
  const btn = document.getElementById("fetchCompsBtn");
  const log = document.getElementById("fetchLog");
  btn.disabled = true;
  document.getElementById("fetchBtnText").textContent = "Fetching...";
  log.innerHTML = "";
  log.classList.add("show");

  const es = new EventSource("/api/fetch_comps");
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.done) {
      es.close();
      btn.disabled = false;
      document.getElementById("fetchBtnText").textContent = "Fetch 5-Year Data";
      log.innerHTML += `<div style="color:#A5D6A7;margin-top:8px">✓ Complete</div>`;
      loadCompsTable();
      loadSidebar();
      return;
    }
    log.innerHTML += `<div>${escHtml(data.msg)}</div>`;
    log.scrollTop = log.scrollHeight;
  };
  es.onerror = () => {
    es.close();
    btn.disabled = false;
    document.getElementById("fetchBtnText").textContent = "Fetch 5-Year Data";
  };
}

function escHtml(s) {
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
</script>
</body>
</html>'''


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/model")
def api_model():
    return jsonify({"model": MODEL})

@app.route("/api/health")
def api_health():
    env_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]
    env_status = {key: bool(os.getenv(key)) for key in env_keys}
    return jsonify({
        "model": MODEL,
        "env_status": env_status,
        "tool_count": len(TOOL_DEFINITIONS),
    })

@app.route("/api/portfolio")
def api_portfolio():
    return jsonify(get_portfolio_summary())

@app.route("/api/comp_count")
def api_comp_count():
    return jsonify({"count": get_comp_count()})

@app.route("/api/comps")
def api_comps():
    return jsonify(get_comps_summary())

@app.route("/api/price_history/<ticker>")
def api_price_history(ticker):
    return jsonify(get_price_history(ticker.upper()))

@app.route("/api/ask")
def api_ask():
    question = request.args.get("q", "")
    if not question:
        return Response("data: {}\n\n", mimetype="text/event-stream")

    q = queue.Queue()

    def run():
        try:
            run_agent_streaming(question, q)
        except Exception as e:
            q.put({"type": "error", "msg": str(e)})

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            try:
                item = q.get(timeout=30)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") in ("answer", "error"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type':'error','msg':'Timeout'})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/api/fetch_comps")
def api_fetch_comps():
    from fetch_comps import fetch_all_comps, ALL_TICKERS
    log_q = queue.Queue()

    def run():
        import sys
        class QueueLogger:
            def write(self, msg):
                if msg.strip():
                    log_q.put({"msg": msg.strip()})
            def flush(self): pass

        old_stdout = sys.stdout
        sys.stdout = QueueLogger()
        try:
            fetch_all_comps(refresh=True)
        finally:
            sys.stdout = old_stdout
        log_q.put({"done": True})

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            try:
                item = log_q.get(timeout=120)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("done"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'done':True})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


if __name__ == "__main__":
    seed_sample_data()
    print(f"\nPortfolio Intelligence Agent")
    print(f"Model: {MODEL}")
    print(f"Open: http://localhost:5000\n")
    app.run(debug=False, port=5000, threaded=True)
