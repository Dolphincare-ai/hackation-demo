"""Build deck.html and deck.pptx from slides.json.

    py -3 -m venv presentation/.venv
    presentation/.venv/Scripts/python -m pip install python-pptx
    presentation/.venv/Scripts/python presentation/build.py
"""
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

HERE = Path(__file__).parent
DECK = json.loads((HERE / "slides.json").read_text(encoding="utf-8"))

BG, PANEL, LINE = "0B1220", "131C2E", "26324A"
TEXT, MUTED, ACCENT, GOOD, WARN, BAD = "E2E8F0", "94A3B8", "38BDF8", "34D399", "FBBF24", "F87171"


# ------------------------------------------------------------------ HTML
HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0b1220;--panel:#131c2e;--line:#26324a;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--good:#34d399;--warn:#fbbf24}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font-family:"Segoe UI",system-ui,sans-serif}
.slide{position:absolute;inset:0;padding:6vh 7vw;display:none;flex-direction:column}
.slide.on{display:flex}
.kicker{color:var(--accent);text-transform:uppercase;letter-spacing:.14em;font-size:1.6vh;font-weight:700;margin-bottom:1.5vh}
h1{font-size:5.2vh;margin:0 0 4vh;line-height:1.15;font-weight:700}
.t-title h1{font-size:9vh;margin-top:22vh}.t-title .sub{font-size:3vh;color:var(--muted);max-width:70vw;line-height:1.4}
.body{flex:1;display:flex;flex-direction:column;justify-content:center;padding-bottom:3vh}
ul{margin:0;padding:0;list-style:none}li{font-size:3.6vh;line-height:1.4;margin:0 0 3.6vh;padding-left:2.6vw;position:relative}
li:before{content:"";position:absolute;left:0;top:1.7vh;width:1.2vh;height:1.2vh;border-radius:50%;background:var(--accent)}
.grid{display:grid;gap:2vw}
.card{background:var(--panel);border:1px solid var(--line);border-radius:1.4vh;padding:3vh 1.6vw}
.card h3{margin:0 0 1.5vh;font-size:2.7vh;color:var(--accent)}.card p,.card li{font-size:2.3vh;color:var(--text);line-height:1.4;margin:0 0 1vh}
.card li{padding-left:1.4vw}.card li:before{width:.7vh;height:.7vh;top:1.1vh}
.cards .card{min-height:46vh;padding:5vh 2vw;border-top:.6vh solid var(--accent)}
.cards .card h3{font-size:3.6vh;margin-bottom:3vh}.cards .card p{font-size:3vh;line-height:1.5}
.flow{display:flex;flex-wrap:nowrap;align-items:center}
.step{background:var(--panel);border:1px solid var(--line);border-top:.6vh solid var(--accent);border-radius:1vh;padding:3vh .8vw;font-size:2.7vh;flex:1;min-width:0;text-align:center;min-height:34vh;display:flex;align-items:center;justify-content:center;line-height:1.35}
.step b{display:block;color:var(--accent);font-size:4.5vh;margin-bottom:1.5vh}.arrow{color:var(--accent);font-size:4vh;padding:0 .3vw}
.footer{color:var(--muted);font-size:2vh;border-top:1px solid var(--line);padding-top:2vh}
.stat{text-align:center;padding:5vh 1vw}.stat .v{font-size:8vh;font-weight:800;color:var(--accent)}.stat .l{font-size:2.2vh;color:var(--muted);margin-top:1vh}
table{border-collapse:collapse;width:100%;font-size:2.2vh}th{color:var(--accent);text-align:left;font-size:1.8vh;text-transform:uppercase;letter-spacing:.08em}
th,td{padding:1.6vh 1vw;border-bottom:1px solid var(--line);vertical-align:top}
.t-demo h1{font-size:4.4vh}.big{font-size:14vh;font-weight:800;color:var(--accent);margin:2vh 0}
.backup .kicker{color:var(--warn)}
#bar{position:fixed;bottom:1.5vh;right:2vw;color:var(--muted);font-size:1.6vh;z-index:5}
#notes{position:fixed;left:0;right:0;bottom:0;background:#000d;padding:2vh 7vw 5vh;font-size:2.2vh;line-height:1.5;display:none;z-index:4;border-top:2px solid var(--accent)}
#notes.on{display:block}#notes b{color:var(--accent)}
@media print{@page{size:landscape}.slide{display:flex!important;position:relative;height:100vh;page-break-after:always}#bar,#notes{display:none!important}}
</style></head><body>
<div id="deck"></div><div id="notes"></div>
<div id="bar"></div>
<script>
const D = __DATA__;
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const ul = xs => "<ul>" + xs.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>";
const foot = s => s.footer ? `<div class="footer">${esc(s.footer)}</div>` : "";
const page = (s, inner) => `<div class="kicker">${esc(s.kicker)}</div><h1>${esc(s.title)}</h1><div class="body">${inner}</div>${foot(s)}`;
const cols = n => `style="grid-template-columns:repeat(${n},1fr)"`;
const R = {
  title: s => `<div class="kicker">${esc(s.kicker)}</div><h1>${esc(s.title)}</h1><div class="sub">${esc(s.subtitle)}</div>`,
  bullets: s => page(s, ul(s.bullets)),
  cards: s => page(s, `<div class="grid cards" ${cols(s.cards.length)}>` +
    s.cards.map(c => `<div class="card"><h3>${esc(c.head)}</h3><p>${esc(c.body)}</p></div>`).join("") + `</div>`),
  flow: s => page(s, `<div class="flow">` +
    s.steps.map((x, i) => `<div class="step"><div><b>${i + 1}</b>${esc(x)}</div></div>`).join('<span class="arrow">›</span>') + `</div>`),
  arch: s => page(s, `<div class="grid" ${cols(s.columns.length)}>` +
    s.columns.map(c => `<div class="card"><h3>${esc(c.head)}</h3>${ul(c.items)}</div>`).join("") + `</div>`),
  stats: s => page(s, `<div class="grid" ${cols(s.stats.length)}>` +
    s.stats.map(x => `<div class="card stat"><div class="v">${esc(x.value)}</div><div class="l">${esc(x.label)}</div></div>`).join("") + `</div>`),
  table: s => page(s, `<table><tr>${s.header.map(h => `<th>${esc(h)}</th>`).join("")}</tr>` +
    s.rows.map(r => "<tr>" + r.map(c => `<td>${esc(c)}</td>`).join("") + "</tr>").join("") + `</table>`),
  demo: s => `<div class="kicker">${esc(s.kicker)}</div><div class="big">Live demo</div><h1>${esc(s.title)}</h1>${ul(s.bullets)}`,
};
const deck = document.getElementById("deck");
D.slides.forEach(s => { const el = document.createElement("section");
  el.className = `slide t-${s.type}${s.backup ? " backup" : ""}`; el.innerHTML = R[s.type](s); deck.appendChild(el); });
const els = [...document.querySelectorAll(".slide")], notes = document.getElementById("notes"), bar = document.getElementById("bar");
let i = Math.max(0, Math.min(els.length - 1, (parseInt(location.hash.slice(1)) || 1) - 1));
const fmt = t => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
const total = D.slides.reduce((a, s) => a + s.seconds, 0);
function show() {
  els.forEach((e, k) => e.classList.toggle("on", k === i));
  const s = D.slides[i], at = D.slides.slice(0, i).reduce((a, x) => a + x.seconds, 0);
  notes.innerHTML = `<b>Notes (${s.seconds ? fmt(s.seconds) : "backup"}):</b> ${esc(s.notes || "")}`;
  bar.textContent = `${i + 1} / ${els.length} · ${s.backup ? "backup" : "at " + fmt(at) + " of " + fmt(total)} · N = notes`;
  history.replaceState(null, "", "#" + (i + 1));
}
document.addEventListener("keydown", e => {
  if (["ArrowRight", "PageDown", " "].includes(e.key)) i = Math.min(els.length - 1, i + 1);
  else if (["ArrowLeft", "PageUp"].includes(e.key)) i = Math.max(0, i - 1);
  else if (e.key.toLowerCase() === "n") notes.classList.toggle("on");
  else if (e.key === "Home") i = 0; else return;
  e.preventDefault(); show();
});
deck.addEventListener("click", e => { i = e.clientX > innerWidth / 3 ? Math.min(els.length - 1, i + 1) : Math.max(0, i - 1); show(); });
show();
</script></body></html>
"""


def build_html():
    out = HTML.replace("__TITLE__", DECK["title"]).replace("__DATA__", json.dumps(DECK, ensure_ascii=False))
    (HERE / "deck.html").write_text(out, encoding="utf-8")


# ------------------------------------------------------------------ PPTX
W, H = Inches(13.333), Inches(7.5)
L, TOP = Inches(0.7), Inches(0.5)
CW = W - 2 * L


def rgb(h):
    return RGBColor.from_string(h)


def text(slide, x, y, w, h, s, size, color=TEXT, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = s
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, rgb(color), "Segoe UI"
    return tf


def bullets(tf_or_slide, items, size, x=None, y=None, w=None, h=None, first=True):
    if x is not None:
        tf = tf_or_slide.shapes.add_textbox(x, y, w, h).text_frame
        tf.word_wrap = True
    else:
        tf, first = tf_or_slide, False
    for k, it in enumerate(items):
        p = tf.paragraphs[0] if (first and k == 0) else tf.add_paragraph()
        p.space_after = Pt(size * 0.6)
        a = p.add_run()
        a.text = "•  "
        a.font.color.rgb, a.font.size, a.font.bold = rgb(ACCENT), Pt(size), True
        b = p.add_run()
        b.text = it
        b.font.color.rgb, b.font.size, b.font.name = rgb(TEXT), Pt(size), "Segoe UI"
    return tf


def box(slide, x, y, w, h, fill=PANEL):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    s.adjustments[0] = 0.06
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    s.line.color.rgb = rgb(LINE)
    s.shadow.inherit = False
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Inches(0.15))
    return s


def para(tf, s, size, color=TEXT, bold=False, first=False, align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(6)
    r = p.add_run()
    r.text = s
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, rgb(color), "Segoe UI"


def header(slide, s, title_size=32):
    text(slide, L, TOP, CW, Inches(0.4), s["kicker"].upper(), 13, WARN if s.get("backup") else ACCENT, bold=True)
    text(slide, L, TOP + Inches(0.4), CW, Inches(1.1), s["title"], title_size, bold=True)
    return TOP + Inches(1.6)


def footer(slide, s):
    if s.get("footer"):
        ln = slide.shapes.add_connector(1, L, H - Inches(1.05), W - L, H - Inches(1.05))
        ln.line.color.rgb = rgb(LINE)
        text(slide, L, H - Inches(0.95), CW, Inches(0.7), s["footer"], 13, MUTED)


def grid(slide, n, y, h):
    gap = Inches(0.25)
    cw = (CW - gap * (n - 1)) / n
    return [(int(L + k * (cw + gap)), y, int(cw), h) for k in range(n)]


def build_pptx():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    for s in DECK["slides"]:
        sl = prs.slides.add_slide(blank)
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = rgb(BG)
        body_h = H - Inches(3.0) if s.get("footer") else H - Inches(2.4)
        t = s["type"]
        if t == "title":
            text(sl, L, Inches(2.0), CW, Inches(0.4), s["kicker"].upper(), 14, ACCENT, bold=True)
            text(sl, L, Inches(2.5), CW, Inches(1.4), s["title"], 60, bold=True)
            text(sl, L, Inches(4.1), Inches(10), Inches(1.5), s["subtitle"], 22, MUTED)
        elif t == "demo":
            text(sl, L, TOP, CW, Inches(0.4), s["kicker"].upper(), 13, ACCENT, bold=True)
            text(sl, L, TOP + Inches(0.5), CW, Inches(1.3), "Live demo", 72, ACCENT, bold=True)
            text(sl, L, TOP + Inches(1.9), CW, Inches(0.7), s["title"], 28, bold=True)
            bullets(sl, s["bullets"], 20, L, TOP + Inches(2.8), CW, Inches(3.8))
        else:
            y = header(sl, s)
            if t == "bullets":
                tf = bullets(sl, s["bullets"], 26, L, y, CW, body_h)
                tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            elif t in ("cards", "arch", "stats"):
                items = s.get("cards") or s.get("columns") or s.get("stats")
                for (x, yy, w, h), c in zip(grid(sl, len(items), y, body_h - Inches(0.2)), items):
                    tf = box(sl, x, yy, w, h).text_frame
                    if t == "stats":
                        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                        para(tf, c["value"], 54, ACCENT, True, first=True, align=PP_ALIGN.CENTER)
                        para(tf, c["label"], 16, MUTED, align=PP_ALIGN.CENTER)
                    elif t == "cards":
                        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                        para(tf, c["head"], 24, ACCENT, True, first=True)
                        para(tf, c["body"], 20)
                    else:
                        para(tf, c["head"], 17, ACCENT, True, first=True)
                        bullets(tf, c["items"], 13)
            elif t == "flow":
                n = len(s["steps"])
                gap = Inches(0.22)
                w = (CW - gap * (n - 1)) / n
                for k, st in enumerate(s["steps"]):
                    x = int(L + k * (w + gap))
                    tf = box(sl, x, y + Inches(0.6), int(w), Inches(3.4)).text_frame
                    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                    para(tf, str(k + 1), 28, ACCENT, True, first=True, align=PP_ALIGN.CENTER)
                    para(tf, st, 15, align=PP_ALIGN.CENTER)
                    if k < n - 1:
                        text(sl, x + int(w) - Inches(0.02), y + Inches(2.0), gap + Inches(0.05), Inches(0.5), "›", 22, ACCENT,
                             bold=True, align=PP_ALIGN.CENTER)
            elif t == "table":
                rows, cols = len(s["rows"]) + 1, len(s["header"])
                tbl = sl.shapes.add_table(rows, cols, L, y, CW, Inches(0.5) * rows).table
                for r, row in enumerate([s["header"]] + s["rows"]):
                    for c, val in enumerate(row):
                        cell = tbl.cell(r, c)
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = rgb(PANEL if r else BG)
                        cell.text = val
                        for p in cell.text_frame.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(13 if r else 12)
                                run.font.bold = r == 0
                                run.font.color.rgb = rgb(ACCENT if r == 0 else TEXT)
                                run.font.name = "Segoe UI"
        footer(sl, s)
        sl.notes_slide.notes_text_frame.text = f"[{s['seconds']}s] {s.get('notes', '')}" if s["seconds"] else s.get("notes", "")
    prs.save(HERE / "deck.pptx")


if __name__ == "__main__":
    build_html()
    build_pptx()
    secs = sum(s["seconds"] for s in DECK["slides"])
    print(f"built deck.html and deck.pptx: {len(DECK['slides'])} slides, {secs // 60}:{secs % 60:02d} timed")
