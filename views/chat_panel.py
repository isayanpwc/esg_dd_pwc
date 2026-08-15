"""
ESG Project Knowledge Panel — complete rewrite.

Architecture
------------
Hidden Streamlit widgets (3 buttons + 1 text input) live in st.sidebar.
The sidebar is a 48px overflow:hidden rail, and JS further force-hides
them. All visible UI (FAB or full panel) is injected into the parent DOM
via a single st.components.v1.html(height=0) call. The JS panel
communicates back to Python by programmatically setting the hidden input
value (via React _valueTracker reset) and clicking the hidden send button.
"""

import streamlit as st
import streamlit.components.v1 as _stc
import html as _html
from datetime import datetime
from utils.chat_assistant import get_response


_QUICK_ACTIONS = [
    "Summarize Project",
    "Explain ESG Score",
    "Key Risks",
    "Compliance Gaps",
    "Regulatory Requirements",
    "View Recommendations",
]


def init_state():
    if "chat_open" not in st.session_state:
        st.session_state["chat_open"] = False
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []
    if "_cp_msg" not in st.session_state:
        st.session_state["_cp_msg"] = ""


def _cb_open():
    st.session_state["chat_open"] = True


def _cb_close():
    st.session_state["chat_open"] = False


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
        {"role": "assistant", "content": resp,
         "time": datetime.now().strftime("%I:%M %p")}
    )


def render_hidden_controls():
    """Render hidden Streamlit widgets in the main area inside a 1px
    fixed-height container — completely invisible to users.
    """
    with st.container(height=1, border=False):
        st.button("_cpo_", key="_cpo_k", on_click=_cb_open)
        st.button("_cpc_", key="_cpc_k", on_click=_cb_close)
        st.text_input("_cpm_", key="_cp_msg", label_visibility="collapsed")
        st.button("_cps_", key="_cps_k", on_click=_cb_send)


def _build_msgs_html(messages):
    if not messages:
        chips = ""
        for qa in _QUICK_ACTIONS:
            e = _html.escape(qa)
            chips += (
                f'<button class="cp-chip" '
                f"onclick=\"window.__cpSend('{e}')\">{e}</button>"
            )
        return (
            '<div class="cp-empty">'
            '<svg width="44" height="44" viewBox="0 0 24 24" fill="none" '
            'stroke="#FF5A00" stroke-width="1.5">'
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14'
            'a2 2 0 0 1 2 2z"/></svg>'
            '<p class="cp-et">How can I help?</p>'
            '<p class="cp-es">Ask about ESG findings, risks, compliance, '
            'reports, or pipeline status.</p>'
            f'<div class="cp-chips">{chips}</div></div>'
        )
    parts = []
    for m in messages:
        escaped = _html.escape(m["content"]).replace("\n", "<br>")
        ts = _html.escape(m.get("time", ""))
        cls = "user" if m["role"] == "user" else "ai"
        parts.append(
            f'<div class="cp-m cp-m-{cls}">'
            f'<div class="cp-b cp-b-{cls}">{escaped}</div>'
            f'<div class="cp-ts">{ts}</div></div>'
        )
    return "".join(parts)


_CSS = r"""
#esg-cp{position:fixed;top:0;right:0;bottom:0;width:420px;
  background:#fff;border-left:1px solid #E5E7EB;z-index:998;
  display:flex;flex-direction:column;
  box-shadow:-4px 0 24px rgba(0,0,0,0.08);
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  animation:cpSlide .3s cubic-bezier(.23,1,.32,1);}
@keyframes cpSlide{from{transform:translateX(100%)}to{transform:translateX(0)}}
#esg-cp *{box-sizing:border-box;}
.cp-hd{padding:16px 18px 14px;border-bottom:1px solid #F3F4F6;
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.cp-hd-l{display:flex;align-items:center;gap:10px;}
.cp-hd-icon{width:36px;height:36px;border-radius:10px;
  background:linear-gradient(135deg,#FF5A00,#FF7F32);
  display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.cp-hd-icon svg{width:20px;height:20px;}
.cp-hd h3{font-size:.95rem;font-weight:700;color:#111827;margin:0;}
.cp-hd p{font-size:.73rem;color:#9CA3AF;margin:2px 0 0;}
.cp-x{background:none;border:none;cursor:pointer;padding:6px;
  color:#9CA3AF;border-radius:6px;transition:all .15s;}
.cp-x:hover{background:#F3F4F6;color:#374151;}
.cp-bd{flex:1;overflow-y:auto;padding:16px 18px;
  display:flex;flex-direction:column;gap:10px;}
.cp-bd::-webkit-scrollbar{width:4px;}
.cp-bd::-webkit-scrollbar-thumb{background:#D1D5DB;border-radius:4px;}
.cp-empty{text-align:center;padding:36px 10px 16px;}
.cp-et{font-size:1rem;font-weight:600;color:#374151;margin:14px 0 4px;}
.cp-es{font-size:.82rem;color:#9CA3AF;line-height:1.5;margin-bottom:18px;}
.cp-chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;}
.cp-chip{padding:7px 14px;border-radius:20px;font-size:.78rem;font-weight:500;
  border:1px solid #FFE4D0;background:#FFF7F2;color:#92400E;
  cursor:pointer;transition:all .15s;font-family:inherit;}
.cp-chip:hover{background:#FF5A00;color:#fff;border-color:#FF5A00;}
.cp-m{display:flex;flex-direction:column;}
.cp-m-user{align-items:flex-end;}
.cp-m-ai{align-items:flex-start;}
.cp-b{max-width:85%;padding:10px 14px;border-radius:14px;
  font-size:.84rem;line-height:1.55;word-wrap:break-word;}
.cp-b-user{background:linear-gradient(135deg,#FF5A00,#FF7F32);
  color:#fff;border-bottom-right-radius:4px;}
.cp-b-ai{background:#F3F4F6;color:#1F2937;border-bottom-left-radius:4px;}
.cp-ts{font-size:.68rem;color:#9CA3AF;margin-top:3px;padding:0 4px;}
.cp-ft{border-top:1px solid #F3F4F6;padding:12px 18px;
  display:flex;gap:8px;align-items:center;flex-shrink:0;}
.cp-inp{flex:1;border:1px solid #E5E7EB;border-radius:12px;
  padding:10px 14px;font-size:.84rem;outline:none;font-family:inherit;
  transition:border-color .2s;}
.cp-inp:focus{border-color:#FF5A00;}
.cp-inp::placeholder{color:#9CA3AF;}
.cp-snd{width:40px;height:40px;border-radius:10px;border:none;
  background:linear-gradient(135deg,#FF5A00,#FF7F32);color:#fff;cursor:pointer;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
  transition:opacity .15s;}
.cp-snd:hover{opacity:.85;}
@keyframes cpDot{0%,80%,100%{transform:scale(0)}40%{transform:scale(1)}}
.cp-typing{display:flex;gap:4px;padding:10px 14px;background:#F3F4F6;
  border-radius:14px 14px 14px 4px;max-width:70px;}
.cp-typing span{width:7px;height:7px;border-radius:50%;background:#9CA3AF;
  display:inline-block;animation:cpDot 1.4s ease-in-out infinite;}
.cp-typing span:nth-child(2){animation-delay:.2s;}
.cp-typing span:nth-child(3){animation-delay:.4s;}
#esg-chat-fab{position:fixed;bottom:28px;right:28px;z-index:1000;}
#esg-chat-fab button{width:56px;height:56px;border-radius:50%;border:none;
  cursor:pointer;background:linear-gradient(135deg,#FF5A00,#FF7F32);
  color:#fff;display:flex;align-items:center;justify-content:center;
  box-shadow:0 4px 16px rgba(255,90,0,0.35);transition:transform .2s,box-shadow .2s;}
#esg-chat-fab button:hover{transform:scale(1.08);
  box-shadow:0 6px 24px rgba(255,90,0,0.45);}
"""

_CHAT_SVG = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
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
        '<div class="cp-hd">'
        '<div class="cp-hd-l">'
        '<div class="cp-hd-icon">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2">'
        '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
        '</svg></div>'
        '<div><h3>AI ESG Assistant</h3>'
        '<p>Ask anything about this project</p></div></div>'
        '<button class="cp-x" id="cpX" title="Close">'
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round">'
        '<line x1="18" y1="6" x2="6" y2="18"/>'
        '<line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>'
        '<div class="cp-bd" id="cpBd">' + msgs_esc + '</div>'
        '<div class="cp-ft">'
        '<input class="cp-inp" id="cpInp" type="text" '
        'placeholder="Ask about ESG findings, risks, reports..." autocomplete="off"/>'
        '<button class="cp-snd" id="cpSnd" title="Send">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<line x1="22" y1="2" x2="11" y2="13"/>'
        '<polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button></div>'
    )
    panel_esc = _e(panel_inner)
    flag = "true" if is_open else "false"

    script = f'''<script>
(function(){{
var D=window.parent.document;
var OPEN={flag};

/* ─ find hidden buttons in main area by label text ─ */
function hBtn(lbl){{
  var main=D.querySelector('div[data-testid="stMainBlockContainer"]');
  if(!main)return null;
  var bs=main.querySelectorAll('button');
  for(var i=0;i<bs.length;i++){{
    if((bs[i].textContent||'').indexOf(lbl)!==-1)return bs[i];
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

/* ─ native React setter ─ */
var _ns=Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype,'value').set;

function setInp(val){{
  var inp=hInp();
  if(!inp||!_ns)return;
  var tr=inp._valueTracker;
  if(tr)tr.setValue('');
  _ns.call(inp,val);
  inp.dispatchEvent(new Event('input',{{bubbles:true}}));
  inp.dispatchEvent(new Event('change',{{bubbles:true}}));
}}

/* ─ cleanup previous injection ─ */
var o1=D.getElementById('esg-cp');if(o1)o1.remove();
var o2=D.getElementById('esg-chat-fab');if(o2)o2.remove();
var o3=D.getElementById('esg-cp-css');if(o3)o3.remove();

/* ─ inject CSS ─ */
var sty=D.createElement('style');
sty.id='esg-cp-css';
sty.textContent=`{css_esc}`;
D.head.appendChild(sty);

if(OPEN){{
  var p=D.createElement('div');p.id='esg-cp';
  p.innerHTML=`{panel_esc}`;
  D.body.appendChild(p);

  var bd=D.getElementById('cpBd');
  if(bd)bd.scrollTop=bd.scrollHeight;

  D.getElementById('cpX').onclick=function(){{
    var b=hBtn('_cpc_');if(b)b.click();
  }};

  window.__cpSend=function(text){{
    if(!text||!text.trim())return;
    text=text.trim();
    if(bd){{
      var um=D.createElement('div');um.className='cp-m cp-m-user';
      um.innerHTML='<div class="cp-b cp-b-user">'
        +text.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</div>';
      bd.appendChild(um);
      var ti=D.createElement('div');ti.className='cp-m cp-m-ai';
      ti.innerHTML='<div class="cp-typing"><span></span><span></span><span></span></div>';
      bd.appendChild(ti);
      bd.scrollTop=bd.scrollHeight;
    }}
    setInp(text);
    setTimeout(function(){{var b=hBtn('_cps_');if(b)b.click();}},250);
  }};

  D.getElementById('cpSnd').onclick=function(){{
    var inp=D.getElementById('cpInp');
    if(inp&&inp.value.trim()){{window.__cpSend(inp.value);inp.value='';}}
  }};
  D.getElementById('cpInp').addEventListener('keydown',function(e){{
    if(e.key==='Enter'&&!e.shiftKey){{
      e.preventDefault();
      var v=this.value.trim();
      if(v){{window.__cpSend(v);this.value='';}}
    }}
  }});
  setTimeout(function(){{var i=D.getElementById('cpInp');if(i)i.focus();}},350);

}}else{{
  var fab=D.createElement('div');fab.id='esg-chat-fab';
  fab.innerHTML='<button title="AI ESG Assistant">{_CHAT_SVG}</button>';
  D.body.appendChild(fab);
  fab.querySelector('button').onclick=function(){{
    var b=hBtn('_cpo_');if(b)b.click();
  }};
}}

}})();
</script>'''

    _stc.html(script, height=0, scrolling=False)
