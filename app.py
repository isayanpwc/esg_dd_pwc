import streamlit as st
import sys
import os
import streamlit as st
import streamlit.components.v1 as _stc
import html as _html
from datetime import datetime
from utils.chat_assistant import get_response

def init_state():
    if "chat_open" not in st.session_state:
        st.session_state["chat_open"] = False
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []
    if "_cp_msg" not in st.session_state:
        st.session_state["_cp_msg"] = ""

def _cb_send():
    msg = st.session_state.get("_cp_msg", "").strip()
    if not msg:
        return
    now = datetime.now().strftime("%I:%M %p")
    st.session_state["chat_messages"].append(
        {"role": "user", "content": msg, "time": now}
    )
    st.session_state["_cp_msg"] = ""
    try:
        resp = get_response(
            msg, st.session_state["chat_messages"][:-1], st.session_state
        )
    except Exception:
        resp = "Information not available in the current project."
    if not resp or not resp.strip():
        resp = "Information not available in the current project."
    st.session_state["chat_messages"].append(
        {"role": "assistant", "content": resp, "time": datetime.now().strftime("%I:%M %p")}
    )

def render_hidden_controls():
    # Hidden widgets: checkbox to control open state, text input for message, button for send
    st.checkbox("Chat Open State", key="chat_open", label_visibility="collapsed")
    st.text_input("Hidden message input", key="_cp_msg", label_visibility="collapsed", placeholder="Ask about this analysis...")
    st.button("Hidden send button", key="_cps_", on_click=_cb_send, label="")

def _build_msgs_html(messages):
    if not messages:
        # Placeholder empty chat message
        return '''
        <div class="cp-empty">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" 
                 stroke="#FF5A00" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <h2>How can I help?</h2>
            <p>Ask me anything about this analysis</p>
        </div>
        '''
    parts = []
    for m in messages:
        escaped = _html.escape(m["content"]).replace("\n", "<br>")
        ts = _html.escape(m.get("time", ""))
        cls = "user" if m["role"] == "user" else "assistant"
        parts.append(
            f'<div class="cp-m cp-m-{cls}">'
            f'<div class="cp-b cp-b-{cls}">{escaped}</div>'
            f'<div class="cp-ts">{ts}</div></div>'
        )
    return "".join(parts)

_CSS = r"""
#esg-cp {
    position: fixed;
    top: 80px;
    right: 24px;
    bottom: 24px;
    width: 360px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 8px 28px rgba(255, 90, 0, 0.25);
    display: flex;
    flex-direction: column;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    z-index: 1100;
    animation: cpSlideIn 0.3s ease forwards;
}
@keyframes cpSlideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
.cp-header {
    display: flex;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid #f2f2f2;
    gap: 12px;
}
.cp-header-icon {
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, #FF5A00, #FF7F32);
    border-radius: 10px;
    display: flex;
    justify-content: center;
    align-items: center;
}
.cp-header-icon svg path {
    stroke: #fff;
}
.cp-header-title {
    flex-grow: 1;
}
.cp-header-title h1 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 700;
    color: #111;
}
.cp-header-title p {
    margin: 2px 0 0 0;
    font-size: 0.85rem;
    color: #999;
    font-weight: 500;
}
.cp-close-btn {
    background: none;
    border: none;
    cursor: pointer;
    color: #999;
    font-size: 22px;
    font-weight: 600;
    padding: 0;
}
.cp-close-btn:hover {
    color: #FF5A00;
}
.cp-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    scrollbar-width: thin;
    scrollbar-color: #ff7f32 #f7f7f7;
}
.cp-body::-webkit-scrollbar {
    width: 7px;
}
.cp-body::-webkit-scrollbar-thumb {
    background-color: #ff7f32;
    border-radius: 10px;
}
.cp-m {
    margin: 6px 0;
}
.cp-m-user {
    text-align: right;
}
.cp-b {
    display: inline-block;
    padding: 12px 16px;
    border-radius: 16px;
    font-size: 0.9rem;
    max-width: 80%;
    line-height: 1.4;
    word-wrap: break-word;
    white-space: pre-wrap;
}
.cp-b-user {
    background: #FF5A00;
    color: white;
    border-bottom-right-radius: 4px;
}
.cp-b-assistant {
    background: #F3F4F6;
    color: #111;
    border-bottom-left-radius: 4px;
}
.cp-ts {
    font-size: 0.68rem;
    color: #999;
    margin-top: 2px;
}
.cp-footer {
    border-top: 1px solid #eee;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.cp-input {
    flex: 1;
    border: 1px solid #ccc;
    border-radius: 20px;
    padding: 10px 16px;
    font-size: 0.9rem;
    outline: none;
    font-family: inherit;
    transition: border-color 0.2s;
}
.cp-input:focus {
    border-color: #FF5A00;
}
.cp-send-button {
    background: #FF5A00;
    border: none;
    border-radius: 50%;
    width: 36px;
    height: 36px;
    color: #fff;
    cursor: pointer;
    display: flex;
    justify-content: center;
    align-items: center;
}
.cp-send-button:hover {
    opacity: 0.85;
}
#esg-chat-fab {
    position: fixed;
    bottom: 28px;
    right: 28px;
    z-index: 1200;
}
#esg-chat-fab button {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    background: linear-gradient(135deg,#FF5A00,#FF7F32);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 16px rgba(255, 90, 0, 0.35);
    transition: transform 0.2s, box-shadow 0.2s;
}
#esg-chat-fab button:hover {
    transform: scale(1.08);
    box-shadow: 0 6px 24px rgba(255, 90, 0, 0.45);
}
@keyframes cpDot {
    0%, 80%, 100% {transform: scale(0);}
    40% {transform: scale(1);}
}
.cp-typing {
    display: flex;
    gap: 6px;
    padding: 10px 14px;
    background: #F3F4F6;
    border-radius: 14px 14px 14px 4px;
    max-width: 70px;
}
.cp-typing span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #9CA3AF;
    display: inline-block;
    animation: cpDot 1.4s ease-in-out infinite;
}
.cp-typing span:nth-child(2) {
    animation-delay: 0.2s;
}
.cp-typing span:nth-child(3) {
    animation-delay: 0.4s;
}
"""

_CHAT_SVG = (
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" '
    'stroke="#fff" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14'
    'a2 2 0 0 1 2 2z"/></svg>'
)

def render_js(is_open):
    messages = st.session_state.get("chat_messages", [])

    def _e(s):
        return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    msgs_esc = _e(_build_msgs_html(messages)) if is_open else ""
    css_esc = _e(_CSS)

    panel_inner = (
        '<div class="cp-header">'
        '<div class="cp-header-icon">'
        + _CHAT_SVG +
        '</div>'
        '<div class="cp-header-title">'
        '<h1>Equil Assistant</h1>'
        '<p>Zenith Industries</p>'
        '</div>'
        '<button class="cp-close-btn" id="cpX" title="Close">&times;</button>'
        '</div>'
        f'<div class="cp-body" id="cpBd">{msgs_esc}</div>'
        '<div class="cp-footer">'
        '<input class="cp-input" id="cpInp" type="text" '
        'placeholder="Ask about this analysis..." autocomplete="off" />'
        '<button class="cp-send-button" id="cpSnd" title="Send">'
        + _CHAT_SVG +
        '</button>'
        '</div>'
    )
    panel_esc = _e(panel_inner)
    flag = "true" if is_open else "false"

    script = f'''<script>
(function(){{
var D=window.parent.document;
var OPEN={flag};

// Functions to find Streamlit hidden widgets
function hCheckbox(){{
  var main=D.querySelector('div[data-testid="stMainBlockContainer"]');
  if(!main)return null;
  var cbs=main.querySelectorAll('input[type="checkbox"]');
  for(var i=0;i<cbs.length;i++){{
    if(cbs[i].closest('div[role="checkbox"]') && cbs[i].id.includes("chat_open")) return cbs[i];
  }}
  return null;
}}
function hInp(){{
  var main=D.querySelector('div[data-testid="stMainBlockContainer"]');
  if(!main)return null;
  var inps=main.querySelectorAll('input[type="text"]');
  for(var i=0;i<inps.length;i++){{
    var c=inps[i].closest('div[data-testid="stVerticalBlockBorderWrapper"]');
    if(c&&c.style&&(parseInt(c.style.height)||0)<=2)return inps[i];
  }}
  return inps.length?inps[inps.length-1]:null;
}}
function hBtn(){{
  var main=D.querySelector('div[data-testid="stMainBlockContainer"]');
  if(!main)return null;
  var bs=main.querySelectorAll('button');
  for(var i=0;i<bs.length;i++){{
    if((bs[i].textContent||'').indexOf("Send hidden button")!==-1)return bs[i];
  }}
  return null;
}}

// Native React input setter
var _ns=Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype,'value').set;

function setInpVal(inp,val){{
  if(!inp||!_ns)return;
  var tr=inp._valueTracker;
  if(tr) tr.setValue('');
  _ns.call(inp,val);
  inp.dispatchEvent(new Event('input',{{bubbles:true}}));
  inp.dispatchEvent(new Event('change',{{bubbles:true}}));
}}

// Remove previous injected nodes and style
var oldPanel=D.getElementById('esg-cp');
if(oldPanel) oldPanel.remove();
var oldFab=D.getElementById('esg-chat-fab');
if(oldFab) oldFab.remove();
var oldStyle=D.getElementById('esg-cp-css');
if(oldStyle) oldStyle.remove();

// Inject styles
var styleNode=D.createElement('style');
styleNode.id='esg-cp-css';
styleNode.textContent=`{css_esc}`;
D.head.appendChild(styleNode);

if(OPEN){{
  // Render chat panel
  var p=D.createElement('div');
  p.id='esg-cp';
  p.innerHTML=`{panel_esc}`;
  D.body.appendChild(p);

  var bd=D.getElementById('cpBd');
  if(bd) bd.scrollTop = bd.scrollHeight;

  D.getElementById('cpX').onclick=function(){{
    var cb=hCheckbox();
    if(cb){{
      cb.checked = false;
      cb.dispatchEvent(new Event('change',{{bubbles:true}}));
    }}
  }};

  window.__cpSend=function(text){{
    if(!text||!text.trim()) return;
    text=text.trim();
    var bd=D.getElementById('cpBd');
    if(bd){{
      var um=D.createElement('div');
      um.className='cp-m cp-m-user';
      um.innerHTML='<div class="cp-b cp-b-user">'
          +text.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</div>';
      bd.appendChild(um);
      var tm=D.createElement('div');
      tm.className='cp-m cp-m-assistant';
      tm.innerHTML='<div class="cp-typing"><span></span><span></span><span></span></div>';
      bd.appendChild(tm);
      bd.scrollTop=bd.scrollHeight;
    }}
    var inp=hInp();
    var btn=hBtn();
    if(inp && btn){{
      setInpVal(inp,text);
      setTimeout(function(){{
        btn.click();
      }}, 100);
    }}
  }};

  D.getElementById('cpSnd').onclick=function(){{
    var inp=D.getElementById('cpInp');
    if(inp && inp.value.trim()){{
      window.__cpSend(inp.value);
      inp.value='';
    }}
  }};
  D.getElementById('cpInp').addEventListener('keydown',function(e){{
    if(e.key==='Enter' && !e.shiftKey){{
      e.preventDefault();
      var v=this.value.trim();
      if(v) {{
        window.__cpSend(v);
        this.value='';
      }}
    }}
  }});
  setTimeout(function(){{
    var i=D.getElementById('cpInp');
    if(i) i.focus();
  }},350);

}} else {{
  // Render floating action button
  var fab=D.createElement('div');
  fab.id='esg-chat-fab';
  fab.innerHTML='<button title="Open Equil Assistant">{_CHAT_SVG}</button>';
  D.body.appendChild(fab);
  fab.querySelector('button').onclick=function(){{
    var cb=hCheckbox();
    if(cb){{
      cb.checked = true;
      cb.dispatchEvent(new Event('change',{{bubbles:true}}));
    }}
  }};
}}
}})();
</script>'''

    _stc.html(script, height=0, scrolling=False)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.auth import is_logged_in
from views import login, home, datasources, registration_agent, metric_analysis_agent, compliance_agent, benchmarking_agent, risk_opportunity_agent, review_governance_agent, settings
from views import chat_panel

st.set_page_config(
    page_title="ESG Data Platform",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Bring a fresh container up to a usable state: schema, and the first Admin if
# bootstrap credentials are supplied. Cached so it runs once per process.
@st.cache_resource
def _bootstrap():
    from esg.bootstrap import initialise

    return initialise()


_BOOT = _bootstrap()

if _BOOT and _BOOT.get("ephemeral"):
    st.warning(
        "**Demo deployment — storage is not durable.** This instance keeps its "
        "database in the container filesystem, which is reset when the Space "
        "rebuilds or sleeps. Anything uploaded here can disappear without "
        "warning, so do not load confidential deal data. Point `DATABASE_URL` at "
        "a managed Postgres instance for real use — see docs/DEPLOYMENT.md.",
        icon="⚠️",
    )


# ══════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════

_BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

*, *::before, *::after {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
/* Preserve Material Symbols icon font — the * selector above overrides the icon
   font, causing ligature text like "upload" to render as a visible duplicate word */
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] * {
    font-family: 'Material Symbols Rounded' !important;
}
.stApp {
    background: linear-gradient(165deg, #FFF8F2 0%, #FFFBF8 40%, #FEFEFE 100%) !important;
}

.stApp > div[data-testid="stAppViewContainer"],
.stApp > div[data-testid="stAppViewContainer"] > div,
div[data-testid="stMain"],
div[data-testid="stMainBlockContainer"],
.stMain, section.main,
section.main > div,
section.main > div > div,
.block-container {
    background: transparent !important;
}

div[data-testid="stHeader"] { visibility: hidden; height: 0; }
#MainMenu, header, footer { visibility: hidden; }
div[data-testid="stAppDeployButton"] { display: none; }

/* ── Hide chat panel control container — visually zero but keeps DOM accessible ── */


/* ── Tabs ── */
div[data-testid="stTabs"] [role="tablist"] {
    gap: 0; border-bottom: 2px solid #E5E7EB; background: transparent;
}
div[data-testid="stTabs"] [role="tab"],
div[data-testid="stTab"] {
    padding: 12px 28px; font-weight: 500; font-size: 0.92rem;
    color: #6B7280; background: transparent; border: none;
    transition: all 0.2s ease;
}
div[data-testid="stTabs"] [aria-selected="true"],
div[data-testid="stTab"][aria-selected="true"] {
    color: #111827 !important; font-weight: 600 !important;
    border-bottom: 3px solid #FF5A00 !important;
}
div[data-testid="stTabs"] [role="tab"]:hover,
div[data-testid="stTab"]:hover { color: #374151 !important; }

/* ── Primary buttons (main area) ── */
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #FF5A00, #FF7F32) !important;
    border: none !important; color: #FFFFFF !important;
    font-weight: 600 !important; border-radius: 12px !important;
    padding: 0.65rem 1.5rem !important; font-size: 0.95rem !important;
    letter-spacing: 0.3px !important;
    transition: all 0.25s cubic-bezier(0.23,1,0.32,1) !important;
    box-shadow: 0 2px 8px rgba(255,90,0,0.20) !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #E65000, #FF6A14) !important;
    box-shadow: 0 6px 20px rgba(255,90,0,0.30) !important;
    transform: translateY(-1px) !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:active {
    transform: translateY(0) !important;
    box-shadow: 0 1px 4px rgba(255,90,0,0.20) !important;
}

/* ── Secondary buttons (main area) ── */
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-secondary"] {
    border: 1px solid #D1D5DB !important; border-radius: 12px !important;
    font-weight: 500 !important; background: #FFFFFF !important;
    color: #374151 !important; padding: 0.55rem 1.2rem !important;
    font-size: 0.92rem !important; transition: all 0.25s ease !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-secondary"]:hover {
    border-color: #FF5A00 !important; color: #FF5A00 !important;
    background: #FFF7F2 !important;
}

/* ── Inputs ── */
div[data-testid="stTextInputRootElement"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stTextInputRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12), 0 1px 3px rgba(0,0,0,0.04) !important;
}
div[data-testid="stTextInputRootElement"]:hover:not(:focus-within) {
    border-color: #D1D5DB !important;
}
div[data-testid="stTextInput"] input {
    border: none !important; background: transparent !important;
    padding: 12px 16px !important; font-size: 0.95rem !important;
    font-weight: 400 !important; color: #111827 !important;
    outline: none !important; box-shadow: none !important;
}
div[data-testid="stTextInput"] input::placeholder { color: #9CA3AF !important; }

div[data-testid="stTextAreaRootElement"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stTextAreaRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12), 0 1px 3px rgba(0,0,0,0.04) !important;
}

div[data-testid="stTextInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stTextArea"] label,
div[data-testid="stCheckbox"] label {
    font-weight: 500 !important; color: #374151 !important;
    font-size: 0.875rem !important; letter-spacing: 0.01em !important;
}

/* ── Selectbox ── */
div[data-testid="stSelectbox"] > div > div {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stSelectbox"] > div > div:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12) !important;
}
div[data-testid="stSelectboxVirtualDropdown"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.10) !important;
}

/* ── Checkbox ── */
div[data-testid="stCheckbox"] label span {
    font-size: 0.85rem; color: #4B5563 !important;
}

/* ── Form card ── */
.form-card {
    background: white; border: 1px solid #E5E7EB;
    border-radius: 16px; padding: 32px; margin-top: 12px;
}

/* ── Section heading ── */
.section-heading {
    font-size: 1.75rem; font-weight: 700; color: #111827;
    margin-bottom: 2px; line-height: 1.25; letter-spacing: -0.02em;
}
.section-heading::after {
    content: ''; display: block; width: 40px; height: 3px;
    background: linear-gradient(90deg, #FF5A00, #FF7F32);
    margin-top: 10px; border-radius: 2px;
}
.section-subtitle {
    color: #6B7280; font-size: 0.9rem; font-weight: 400;
    margin-top: 6px; margin-bottom: 0; line-height: 1.6;
}

/* ── Error / Alert ── */
div[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Expander — fix icon/text overlap ── */
div[data-testid="stExpander"] {
    border: 1px solid #E5E7EB !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    margin-bottom: 12px !important;
}
div[data-testid="stExpander"] details > summary {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    padding: 12px 16px !important;
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: #374151 !important;
    cursor: pointer !important;
    white-space: normal !important;
    word-break: break-word !important;
    overflow: visible !important;
    position: relative !important;
    list-style: none !important;
}
div[data-testid="stExpander"] details > summary::-webkit-details-marker {
    display: none !important;
}
div[data-testid="stExpander"] details > summary > span {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
div[data-testid="stExpander"] summary svg,
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] svg {
    flex-shrink: 0 !important;
    width: 16px !important;
    height: 16px !important;
    min-width: 16px !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
    width: 20px !important;
    height: 20px !important;
    overflow: hidden !important;
    font-size: 0 !important;
    line-height: 0 !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] svg {
    font-size: initial !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 0 16px 16px 16px !important;
}

/* ── Hide Streamlit internal accessibility text that leaks visually ── */
div[data-testid="stExpander"] summary span[data-testid],
div[data-testid="stExpander"] summary .css-0,
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] span {
    font-size: 0 !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    position: absolute !important;
    clip: rect(0, 0, 0, 0) !important;
    white-space: nowrap !important;
    border: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* ── File uploader — styling ── */
div[data-testid="stFileUploader"] > div > div {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    background: #FFFAF7 !important;
}
div[data-testid="stFileUploader"] button {
    border-radius: 10px !important;
    flex-shrink: 0 !important;
}

/* ── Generic flex/icon-text overlap prevention ── */
div[data-testid="stMarkdownContainer"] > div[style*="display:flex"],
div[data-testid="stMarkdownContainer"] > div[style*="display: flex"] {
    overflow: visible !important;
}
div[data-testid="stMarkdownContainer"] > div[style*="display:flex"] > *,
div[data-testid="stMarkdownContainer"] > div[style*="display: flex"] > * {
    position: relative !important;
}

/* ── Tab labels — prevent overlap on narrow screens ── */
div[data-testid="stTabs"] [role="tab"] {
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    min-width: 0 !important;
}

/* ── Selectbox / multi-select — prevent label overlap ── */
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label {
    display: block !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}

/* ── Focus a11y ── */
*:focus-visible { outline: 2px solid #FF5A00 !important; outline-offset: 2px !important; }
</style>
"""

_HIDE_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] { display: none !important; width: 0 !important; min-width: 0 !important; }
button[data-testid="stSidebarCollapseButton"] { display: none !important; }
div[data-testid="stSidebarCollapsedControl"] { display: none !important; visibility: hidden !important; width: 0 !important; height: 0 !important; overflow: hidden !important; }
div[data-testid="stAppViewContainer"] { margin-left: 0 !important; }
[data-testid="stSidebarNav"] { display: none !important; }
</style>
"""

_SIDEBAR_CSS = """
/* ═══ Sidebar — hover-expand rail ═══ */

button[data-testid="stSidebarCollapseButton"],
button[data-testid="baseButton-headerNoPadding"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important; height: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
    position: absolute !important;
    overflow: hidden !important;
}
div[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important; height: 0 !important;
    pointer-events: none !important;
}
[data-testid="stSidebarNav"] { display: none !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"] button[kind="headerNoPadding"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important; height: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}

/* --- sidebar shell --- */
section[data-testid="stSidebar"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: fixed !important;
    top: 0 !important; left: 0 !important; bottom: 0 !important;
    width: 48px !important;
    min-width: 0 !important;
    max-width: 48px !important;
    height: 100vh !important;
    background: #FFFFFF !important;
    border-right: 1px solid #E5E7EB !important;
    z-index: 999 !important;
    transform: none !important;
    box-shadow: none !important;
    overflow: hidden !important;
    transition: width 0.3s cubic-bezier(0.23,1,0.32,1),
                max-width 0.3s cubic-bezier(0.23,1,0.32,1),
                box-shadow 0.3s ease !important;
}
section[data-testid="stSidebar"].expanded {
    width: 220px !important;
    max-width: 220px !important;
    box-shadow: 4px 0 24px rgba(0,0,0,0.10) !important;
}

div[data-testid="stAppViewContainer"] {
    margin-left: 48px !important;
    transition: margin-left 0.3s cubic-bezier(0.23,1,0.32,1) !important;
}

/* ── Main content full-width ── */
div[data-testid="stMainBlockContainer"],
div[data-testid="stAppViewContainer"] .block-container,
.main .block-container {
    max-width: 100% !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    padding-top: 1rem !important;
}

/* --- reset Streamlit nested wrappers --- */
section[data-testid="stSidebar"] > div {
    background: transparent !important;
    padding: 0 !important;
    padding-top: 6px !important;
    margin: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    height: 100vh !important;
    overflow: visible !important;
    width: 220px !important;
    min-width: 220px !important;
}
section[data-testid="stSidebar"] > div > div,
section[data-testid="stSidebar"] > div > div > div,
section[data-testid="stSidebar"] > div > div > div > div,
section[data-testid="stSidebar"] > div > div > div > div > div {
    background: transparent !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: visible !important;
}
section[data-testid="stSidebar"] .block-container { padding: 0 !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding: 0 !important;
    margin: 0 !important;
    overflow: visible !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding: 0 !important;
    margin: 0 !important;
    overflow: visible !important;
    display: flex !important;
    flex-direction: column !important;
    height: 100vh !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div:first-child {
    padding: 0 !important; margin: 0 !important;
    flex: 1 !important; display: flex !important; flex-direction: column !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0 !important; padding: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
    padding: 0 !important; margin: 0 !important;
}
section[data-testid="stSidebar"] .stElementContainer,
section[data-testid="stSidebar"] [data-testid="stElementContainer"],
section[data-testid="stSidebar"] [data-testid="element-container"] {
    margin: 0 !important; padding: 0 !important;
}
section[data-testid="stSidebar"] .stMarkdown p { margin: 0 !important; }
section[data-testid="stSidebar"] .stMarkdown { margin: 0 !important; padding: 0 !important; }
section[data-testid="stSidebar"] .stButton { margin: 0 !important; padding: 0 !important; }

/* --- nav buttons --- */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    width: 220px !important;
    height: 38px !important;
    min-height: 38px !important;
    max-height: 38px !important;
    margin: 0 !important;
    padding: 0 0 0 14px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    border-radius: 0 !important;
    cursor: pointer !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    box-sizing: border-box !important;
    position: relative !important;
    box-shadow: none !important;
    overflow: hidden !important;
    transition: background 0.15s ease, border-color 0.15s ease !important;
}

/* inactive */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background: transparent !important;
}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
    background: #FFF7ED !important;
}

/* active */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    background: #FFF7ED !important;
    box-shadow: none !important;
    border-left: 3px solid #E86B2E !important;
}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
    background: #FFEDD5 !important;
}

/* --- button text: collapsed = icon only, expanded = icon + label --- */
section[data-testid="stSidebar"] button p {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    gap: 12px !important;
    margin: 0 !important;
    padding: 0 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    width: 200px !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: #374151 !important;
    line-height: 1 !important;
    transition: color 0.2s ease !important;
}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p {
    color: #9A3412 !important;
    font-weight: 600 !important;
}

/* icon sizing */
section[data-testid="stSidebar"] button p svg.nav-icon {
    flex-shrink: 0 !important;
    width: 18px !important; min-width: 18px !important; max-width: 18px !important;
    height: 18px !important; min-height: 18px !important; max-height: 18px !important;
    display: block !important;
}

/* --- profile block --- */
section[data-testid="stSidebar"] .sidebar-profile {
    overflow: hidden !important;
    white-space: nowrap !important;
}

/* --- header: app icon + title --- */
section[data-testid="stSidebar"] .sidebar-header {
    display: flex !important;
    align-items: center !important;
    min-height: 36px !important;
    height: 36px !important;
    padding: 0 0 0 14px !important;
    overflow: visible !important;
    white-space: nowrap !important;
    box-sizing: border-box !important;
    margin: 0 !important;
}
section[data-testid="stSidebar"] .sidebar-header .sh-icon {
    flex-shrink: 0 !important;
    width: 20px !important; height: 20px !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
    transition: opacity 0.2s ease !important;
    overflow: visible !important;
}
section[data-testid="stSidebar"] .sidebar-header .sh-title {
    margin-left: 10px !important;
    font-size: 0.95rem !important;
    font-weight: 800 !important;
    color: #1F2937 !important;
    font-family: Inter, sans-serif !important;
    letter-spacing: -0.02em !important;
    line-height: 1.15 !important;
    opacity: 0 !important;
    transition: opacity 0.18s ease 0.08s !important;
}
section[data-testid="stSidebar"].expanded .sidebar-header .sh-icon {
    opacity: 0 !important;
    width: 0 !important;
    overflow: hidden !important;
    transition: opacity 0.1s ease, width 0s ease 0.1s !important;
}
section[data-testid="stSidebar"].expanded .sidebar-header .sh-title {
    opacity: 1 !important;
    margin-left: 5px !important;
}
"""


def _get_sidebar_css():
    return f"<style>{_SIDEBAR_CSS}</style>"


# ══════════════════════════════════════════════════════════════
#  NAVIGATION DATA
# ══════════════════════════════════════════════════════════════

_NAV_ITEMS = [
    ("Home",                "home"),
    ("Data Sources",        "datasources"),
    ("Registration",        "registration_agent"),
    ("Metric Analysis",     "metric_analysis"),
    ("Regulatory Tracker",  "compliance_agent"),
    ("Benchmarking",        "benchmarking"),
    ("Risk & Opportunities","risk_opportunity"),
    ("Review & Reporting",  "review_governance"),
]


def _set_page(target):
    st.session_state["page"] = target



def _nav_btn(label, target, current_page):
    btn_type = "primary" if current_page == target else "secondary"
    st.button(label, key=f"nav_{target}", use_container_width=True,
              type=btn_type, on_click=_set_page, args=(target,))


# ══════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════

_SIDEBAR_ICONS = {
    "home":               '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "datasources":        '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    "registration_agent": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "metric_analysis":    '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "compliance_agent":   '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "benchmarking":       '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "risk_opportunity":   '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "review_governance":  '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M12 18v-4"/><path d="M8 18v-2"/><path d="M16 18v-6"/>',
    "logout":             '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
}

_SIDEBAR_JS_TEMPLATE = """
var icons = __ICONS__;
var activePage = '__ACTIVE_PAGE__';
var targets = __TARGETS__;
var labels = __LABELS__;
var doc = window.parent.document;

function initSidebar() {
    var sb = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sb) return false;
    if (sb.dataset.hoverBound) return true;

    sb.setAttribute('aria-expanded', 'true');
    sb.style.setProperty('transform', 'none', 'important');
    sb.style.setProperty('visibility', 'visible', 'important');
    sb.style.setProperty('display', 'flex', 'important');

    var collapseTimer = null;
    function setExpanded(open) {
        if (open) {
            sb.classList.add('expanded');
        } else {
            sb.classList.remove('expanded');
        }
        var av = doc.querySelector('div[data-testid="stAppViewContainer"]');
        if (av) av.style.setProperty('margin-left', open ? '220px' : '48px', 'important');
    }
    sb.addEventListener('mouseenter', function() {
        if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; }
        setExpanded(true);
    });
    sb.addEventListener('mouseleave', function() {
        collapseTimer = setTimeout(function() { setExpanded(false); }, 350);
    });
    sb.dataset.hoverBound = '1';
    return true;
}
initSidebar();
var _sbA = 0;
var _sbI = setInterval(function() { _sbA++; if (initSidebar() || _sbA >= 50) clearInterval(_sbI); }, 100);

function injectIcons() {
    var sidebar = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sidebar) return false;
    var btns = sidebar.querySelectorAll('.stButton button');
    if (btns.length === 0) return false;
    var ok = 0;
    for (var i = 0; i < btns.length && i < targets.length; i++) {
        var t = targets[i];
        var pathData = icons[t];
        if (!pathData) continue;
        var p = btns[i].querySelector('p');
        if (!p) continue;
        if (p.querySelector('svg.nav-icon')) { ok++; continue; }
        var isActive = (t === activePage);
        var color = isActive ? '#E86B2E' : '#6B7280';
        var svg = '<svg class="nav-icon" xmlns="http://www.w3.org/2000/svg" '
            + 'width="18" height="18" viewBox="0 0 24 24" fill="none" '
            + 'stroke="' + color + '" stroke-width="1.75" '
            + 'stroke-linecap="round" stroke-linejoin="round" '
            + 'style="display:block;flex-shrink:0;width:18px;height:18px;">'
            + pathData + '</svg>';
        var tmp = doc.createElement('div');
        tmp.innerHTML = svg;
        var el = tmp.firstChild;
        if (el) p.insertBefore(el, p.firstChild);
        ok++;
    }
    return ok > 0;
}
injectIcons();
var _ia = 0;
var _ii = setInterval(function() {
    _ia++;
    if (injectIcons() || _ia >= 50) clearInterval(_ii);
}, 100);

function findVBlockParent(el) {
    while (el && el.parentElement) {
        var pid = el.parentElement.getAttribute
            ? el.parentElement.getAttribute('data-testid') : null;
        if (pid === 'stVerticalBlock' || pid === 'stSidebarUserContent') return el;
        el = el.parentElement;
    }
    return null;
}

function pinElements() {
    var sidebar = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sidebar) return false;
    var logoutWrap = null;
    var allBtns = sidebar.querySelectorAll('.stButton');
    for (var bi = 0; bi < allBtns.length; bi++) {
        var b = allBtns[bi].querySelector('button');
        if (b && (b.textContent || '').trim() === 'Logout') { logoutWrap = allBtns[bi]; break; }
    }
    if (!logoutWrap) return false;
    if (logoutWrap.dataset.pinned) return true;

    var header = sidebar.querySelector('.sidebar-header');
    var profile = sidebar.querySelector('.sidebar-profile');

    if (header) {
        var headerC = findVBlockParent(header);
        if (headerC) {
            headerC.style.setProperty('width', '220px', 'important');
            headerC.style.setProperty('margin', '0', 'important');
            headerC.style.setProperty('padding', '0', 'important');
            headerC.style.setProperty('overflow', 'visible', 'important');
            headerC.style.setProperty('min-height', '36px', 'important');
        }
        var el = header;
        while (el && el.parentElement) {
            var p = el.parentElement;
            if (p.getAttribute && p.getAttribute('data-testid') === 'stSidebar') break;
            p.style.setProperty('overflow', 'visible', 'important');
            p.style.setProperty('padding-top', '0', 'important');
            p.style.setProperty('margin-top', '0', 'important');
            el = p;
        }
    }

    var logoutC = findVBlockParent(logoutWrap);
    if (logoutC) {
        logoutC.style.setProperty('position', 'absolute', 'important');
        logoutC.style.setProperty('bottom', '12px', 'important');
        logoutC.style.setProperty('left', '0', 'important');
        logoutC.style.setProperty('width', '220px', 'important');
    }

    if (profile) {
        var profileC = findVBlockParent(profile);
        if (profileC) {
            profileC.style.setProperty('position', 'absolute', 'important');
            profileC.style.setProperty('bottom', '60px', 'important');
            profileC.style.setProperty('left', '0', 'important');
            profileC.style.setProperty('width', '220px', 'important');
        }
    }

    logoutWrap.dataset.pinned = '1';
    return true;
}
pinElements();
var _pa = 0;
var _pi = setInterval(function() {
    _pa++;
    if (pinElements() || _pa >= 50) clearInterval(_pi);
}, 100);

"""


def _render_sidebar():
    import json
    from utils.auth import logout_user, get_current_user, get_current_role

    page = st.session_state.get("page", "datasources")
    user = get_current_user() or "User"
    role = get_current_role() or "Viewer"

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-header">'
            '<div class="sh-icon">'
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="#E86B2E" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round">'
            '<rect x="3" y="3" width="7" height="7"/>'
            '<rect x="14" y="3" width="7" height="7"/>'
            '<rect x="3" y="14" width="7" height="7"/>'
            '<rect x="14" y="14" width="7" height="7"/>'
            '</svg></div>'
            '<div class="sh-title">ESG Due Diligence</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        for label, target in _NAV_ITEMS:
            _nav_btn(label, target, page)

        st.markdown(
            f'<div class="sidebar-profile" style="padding:8px 14px;'
            f'display:flex;align-items:center;gap:10px;">'
            f'<div style="width:28px;height:28px;border-radius:50%;'
            f'background:#F3F4F6;display:flex;align-items:center;'
            f'justify-content:center;flex-shrink:0;">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
            f'stroke="#6B7280" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round">'
            f'<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>'
            f'<circle cx="12" cy="7" r="4"/></svg></div>'
            f'<div style="overflow:hidden;white-space:nowrap;">'
            f'<div style="font-size:0.8rem;font-weight:600;color:#1F2937;'
            f'line-height:1.2;">{user}</div>'
            f'<div style="font-size:0.7rem;color:#9CA3AF;'
            f'line-height:1.2;">{role}</div></div></div>',
            unsafe_allow_html=True,
        )

        st.button("Logout", key="nav_logout", use_container_width=True,
                  type="secondary", on_click=logout_user)

        all_nav = list(_NAV_ITEMS) + [("Logout", "logout")]
        all_targets = [t for _, t in all_nav]
        all_labels = [l for l, _ in all_nav]
        js_body = _SIDEBAR_JS_TEMPLATE.replace('__ACTIVE_PAGE__', page)
        js_body = js_body.replace('__TARGETS__', json.dumps(all_targets))
        js_body = js_body.replace('__LABELS__', json.dumps(all_labels))
        js_body = js_body.replace('__ICONS__', json.dumps(_SIDEBAR_ICONS))
        import streamlit.components.v1 as _stc
        _stc.html(
            "<html><head><script>" + js_body + "</script></head>"
            "<body></body></html>",
            height=0, scrolling=False,
        )


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    if "page" not in st.session_state:
        st.session_state["page"] = "login"
    if not is_logged_in():
        st.session_state["page"] = "login"

    st.markdown(_BASE_CSS, unsafe_allow_html=True)

    page = st.session_state["page"]

    if page == "login":
        st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
        login.render()
    else:
        chat_panel.init_state()
        chat_open = st.session_state["chat_open"]

        _mr = "420px" if chat_open else "0"
        st.markdown(
            '<style>'
            'div[data-testid="stAppViewContainer"]{'
            f'  margin-right:{_mr} !important;'
            '  transition:margin-right 0.3s cubic-bezier(0.23,1,0.32,1) !important;'
            '}'
            '</style>',
            unsafe_allow_html=True,
        )

        st.markdown(_get_sidebar_css(), unsafe_allow_html=True)
        _render_sidebar()
        chat_panel.render_hidden_controls()

        if page == "registration_agent":
            registration_agent.render()
        elif page == "metric_analysis":
            metric_analysis_agent.render()
        elif page == "compliance_agent":
            compliance_agent.render()
        elif page == "benchmarking":
            benchmarking_agent.render()
        elif page == "risk_opportunity":
            risk_opportunity_agent.render()
        elif page == "review_governance":
            review_governance_agent.render()
        elif page == "datasources":
            datasources.render()
        elif page == "settings":
            settings.render()
        else:
            home.render()

        chat_panel.render_js(chat_open)


if __name__ == "__main__":
    main()
