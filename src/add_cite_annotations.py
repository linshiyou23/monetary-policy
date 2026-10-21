# -*- coding: utf-8 -*-
"""把 site/ 三个 HTML 中的（手册N §X.Y）引用改为悬停批注气泡。

输入：sources/txt/_chunkK.json + _quotes_K.json（子代理产出的引用→原文对照，仅本地留存）
用法：python -X utf8 src/add_cite_annotations.py [--dry-run]
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TXT = ROOT / "sources" / "txt"
FILES = ["site/framework.html", "site/evolution.html", "site/stages.html"]
CITE = re.compile(r"（(手册[一二三四五六][^（）]{0,60}?)）")

CSS = """
/* 悬停批注（出处＋报告原文摘录） */
.a { position: relative; border-bottom: 1px dotted #6d95c9; cursor: help; }
.a > .pop { display: none; position: absolute; left: 0; top: calc(100% + 8px); z-index: 40;
  width: min(560px, 82vw); padding: 10px 14px; background: #fffdf3; border: 1px solid #d9c78f;
  border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.18); font-size: 13.5px; line-height: 1.8;
  color: #4a3f24; text-align: left; cursor: auto; }
.a:hover > .pop, .a:focus > .pop { display: block; }
.a > .pop .src { color: var(--accent); font-weight: 600; }
.cite-badge { font-size: 13px; color: var(--muted); }
@media print { .a > .pop { display: none !important; } .a { border-bottom: none; } }
"""

JS = """
<script>
(function () {
  function place(el) {
    var pop = el.querySelector('.pop');
    if (!pop) return;
    pop.style.display = 'block';
    var pw = Math.min(560, innerWidth * 0.82);
    pop.style.position = 'fixed';
    pop.style.width = pw + 'px';
    var r = el.getBoundingClientRect(), ph = pop.offsetHeight;
    var top = r.bottom + 8;
    if (top + ph > innerHeight - 8) top = r.top - ph - 8;
    if (top < 8) top = 8;
    var left = r.left;
    if (left + pw > innerWidth - 8) left = innerWidth - 8 - pw;
    if (left < 8) left = 8;
    pop.style.top = top + 'px';
    pop.style.left = left + 'px';
  }
  function hide(el) {
    var pop = el.querySelector('.pop');
    if (!pop) return;
    pop.style.display = '';
    pop.style.position = '';
  }
  document.querySelectorAll('.a').forEach(function (el) {
    el.addEventListener('mouseenter', function () { place(el); });
    el.addEventListener('focus', function () { place(el); });
    el.addEventListener('mouseleave', function () { hide(el); });
    el.addEventListener('blur', function () { hide(el); });
  });
})();
</script>
"""

INTRO_REPLACEMENTS = {
    "site/framework.html": (
        "括号内为出处，如（手册一 §2.1.1）指《手册一：初识央行资产负债表》第 2.1.1 节。",
        "出处不再写在正文括号里：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录（如“手册一 §2.1.1”指《手册一：初识央行资产负债表》第 2.1.1 节）。",
    ),
    "site/evolution.html": (
        "括号内为出处。",
        "出处以悬停批注显示：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录。",
    ),
    "site/stages.html": (
        "括号内为出处。",
        "出处以悬停批注显示：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录。",
    ),
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pop_html(cite, quote, page):
    src = f'<span class="src">出处：{esc(cite)}</span>'
    if page:
        src += f'（{esc(page)}）'
    body = f'<br>原文：“{esc(quote)}”' if quote else ''
    return f'<span class="pop">{src}{body}</span>'


def load_quotes():
    """合并 chunk 与 quotes：{(file, i): {cite, quote, page}}"""
    quotes = {}
    for k in range(1, 7):
        chunk = json.loads((TXT / f"_chunk{k}.json").read_text(encoding="utf-8"))
        qd = {q["i"]: q for q in json.loads((TXT / f"_quotes_{k}.json").read_text(encoding="utf-8"))}
        assert set(qd) == {c["i"] for c in chunk}, f"chunk{k}: i 集合不一致"
        for c in chunk:
            q = qd[c["i"]]
            quotes[(c["file"], c["i"])] = {"cite": c["cite"], "quote": q.get("quote"), "page": q.get("page")}
    return quotes


def validate_quotes(quotes, dumps):
    bad = []
    for (f, i), q in quotes.items():
        if not q.get("quote"):
            continue
        m = re.search(r"手册([一二三四五六])", q.get("page") or q["cite"])
        dump = dumps.get("手册" + m.group(1)) if m else None
        if dump is None:
            bad.append((f, i, "no dump"))
            continue
        flat = re.sub(r"\s+", "", dump)
        for frag in q["quote"].split("……"):
            if re.sub(r"\s+", "", frag) not in flat:
                bad.append((f, i, frag[:40]))
    return bad


def transform(fname, quotes, dry=False):
    path = ROOT / fname
    t = path.read_text(encoding="utf-8")
    is_stages = "stages" in fname
    matches = list(CITE.finditer(t))
    n_expected = sum(1 for (f, _) in quotes if f == fname)
    assert len(matches) == n_expected, f"{fname}: 引用数 {len(matches)} != quotes {n_expected}"
    unknown = []
    for idx in range(len(matches) - 1, -1, -1):
        m = matches[idx]
        i = idx + 1
        if fname == "site/framework.html" and i == 1:
            continue  # 导语解释句，随导语整体改写
        q = quotes[(fname, i)]
        cite, quote, page = q["cite"], q.get("quote"), q.get("page")
        li_s = t.rfind("<li", 0, m.start()); li_e = t.find("</li>", m.start())
        p_s = t.rfind("<p", 0, m.start()); p_e = t.find("</p>", m.start())
        b_s = max(li_s, p_s)
        b_e = min(x for x in (li_e, p_e) if x != -1)
        o_e = t.find(">", b_s) + 1                 # 越过 <p> / <li> 开标签
        content = t[o_e:b_e]
        cs, ce = m.start() - o_e, m.end() - o_e    # 引用在 content 内的位置
        after = t[m.end():m.end() + 8]
        if content.strip() == m.group(0):
            # 表格下的独立出处段 → 可见徽标＋气泡
            new_content = (f'<span class="a" tabindex="0">〔出处〕{esc(cite)}'
                           f'{pop_html(cite, quote, page)}</span>')
        elif is_stages:
            ls = content.rfind("\n", 0, cs)
            ls = ls + 1 if ls != -1 else 0
            if content[ls:cs].lstrip().startswith("- "):
                line = re.sub(r"^\s*- ", "", content[ls:cs])
                new_content = (content[:ls] + '- <span class="a" tabindex="0">' + line
                               + pop_html(cite, quote, page) + '</span>' + content[ce:])
            else:
                new_content = ('<span class="a" tabindex="0">' + content[:cs]
                               + pop_html(cite, quote, page) + '</span>' + content[ce:])
        elif re.match(r"\s*(</li>|</p>)", after):
            new_content = ('<span class="a" tabindex="0">' + content[:cs]
                           + pop_html(cite, quote, page) + '</span>' + content[ce:])
        elif content[max(0, cs - 9):cs] == "</strong>" and after.startswith("："):
            s_s = content.rfind("<strong>", 0, cs)
            new_content = (content[:s_s] + '<span class="a" tabindex="0">' + content[s_s:cs]
                           + pop_html(cite, quote, page) + '</span>' + content[ce:])
        else:
            unknown.append((fname, i, cite))
            continue
        t = t[:o_e] + new_content + t[b_e:]
    old, new = INTRO_REPLACEMENTS[fname]
    assert old in t, f"{fname}: 导语句未找到"
    t = t.replace(old, new)
    assert t.count("</style>") == 1 and t.count("</body>") == 1
    t = t.replace("</style>", CSS + "</style>")
    t = t.replace("</body>", JS + "\n</body>")
    if not dry:
        path.write_text(t, encoding="utf-8")
    return len(matches), unknown


def main():
    dry = "--dry-run" in sys.argv
    dumps = {p.stem: p.read_text(encoding="utf-8") for p in TXT.glob("手册*.txt")}
    quotes = load_quotes()
    print("quotes loaded:", len(quotes))
    nulls = sorted((f, i) for (f, i), q in quotes.items() if not q.get("quote"))
    print("null quotes:", len(nulls), nulls[:10])
    bad = validate_quotes(quotes, dumps)
    if bad:
        print("VALIDATION FAILURES:")
        for b in bad:
            print("  ", b)
        sys.exit(1)
    print("validation ok: 每条引文均为对应手册文本的逐字子串")
    total = 0
    for f in FILES:
        n, unknown = transform(f, quotes, dry)
        total += n
        print(f"{f}: {n} 处引用已处理; 未识别形态: {unknown}")
    print("total", total, "(dry-run)" if dry else "(written)")


if __name__ == "__main__":
    main()
