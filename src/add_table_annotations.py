# -*- coding: utf-8 -*-
"""表格"出处"列改为行悬停批注；并去掉句级批注下划线、更新导语与 CSS/JS。

输入：sources/txt/_tchunkK.json + _tquotes_K.json（表格行→原文对照，仅本地留存）
用法：python -X utf8 src/add_table_annotations.py [--dry-run]
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TXT = ROOT / "sources" / "txt"
sys.path.insert(0, str(ROOT / "src"))
from add_cite_annotations import CSS as OLD_CSS, JS as OLD_JS, pop_html  # noqa: E402

FILES = ["site/framework.html", "site/evolution.html", "site/stages.html"]

NEW_CSS = """
/* 悬停批注（出处＋报告原文摘录）：句子与表格行共用气泡样式 */
.a { position: relative; cursor: help; }
.a-row { cursor: help; }
.a-row td:first-child { position: relative; }
.a > .pop, .a-row .pop { display: none; position: absolute; left: 0; top: calc(100% + 8px); z-index: 40;
  width: min(560px, 82vw); padding: 10px 14px; background: #fffdf3; border: 1px solid #d9c78f;
  border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.18); font-size: 13.5px; line-height: 1.8;
  color: #4a3f24; text-align: left; cursor: auto; }
.a:hover > .pop, .a:focus > .pop, .a-row:hover .pop, .a-row:focus .pop { display: block; }
.pop .src { color: var(--accent); font-weight: 600; }
.cite-badge { font-size: 13px; color: var(--muted); }
@media print { .a > .pop, .a-row .pop { display: none !important; } }
"""

INTRO_REPLACEMENTS = {
    "site/framework.html": (
        "出处不再写在正文括号里：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录（如“手册一 §2.1.1”指《手册一：初识央行资产负债表》第 2.1.1 节）。",
        "出处以悬停批注显示：鼠标悬停在句子或表格行上，即可查看出处与报告原文摘录（如“手册一 §2.1.1”指《手册一：初识央行资产负债表》第 2.1.1 节）。",
    ),
    "site/evolution.html": (
        "出处以悬停批注显示：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录。",
        "出处以悬停批注显示：鼠标悬停在句子或表格行上，即可查看出处与报告原文摘录。",
    ),
    "site/stages.html": (
        "出处以悬停批注显示：鼠标悬停在带虚线下划线的句子上，即可查看出处与报告原文摘录。",
        "出处以悬停批注显示：鼠标悬停在句子或表格行上，即可查看出处与报告原文摘录。",
    ),
}


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def load_rows():
    rows = {}
    for k in (1, 2):
        chunk = json.loads((TXT / f"_tchunk{k}.json").read_text(encoding="utf-8"))
        qd = {q["i"]: q for q in json.loads((TXT / f"_tquotes_{k}.json").read_text(encoding="utf-8"))}
        assert set(qd) == {c["i"] for c in chunk}, f"tchunk{k}: i 集合不一致"
        for c in chunk:
            q = qd[c["i"]]
            rows[(c["file"], c["i"])] = {"cite": c["cite"], "quote": q.get("quote"), "page": q.get("page")}
    return rows


def validate(rows, dumps):
    bad = []
    for (f, i), q in rows.items():
        if not q.get("quote"):
            bad.append((f, i, "null quote"))
            continue
        srcs = set(re.findall(r"手册([一二三四五六])", (q.get("page") or "") + " " + q["cite"]))
        flats = [re.sub(r"\s+", "", dumps.get("手册" + s, "")) for s in srcs]
        for frag in q["quote"].split("……"):
            fr = re.sub(r"\s+", "", frag)
            # page 为多来源时，片段在任一涉及手册中逐字命中即可
            if not any(fr in fl for fl in flats if fl):
                bad.append((f, i, frag[:40]))
    return bad


def transform_file(fname, rows, dry=False):
    # 清单 i 为跨文件全局编号，此处按文件内顺序重新编排
    rows_list = [rows[(fname, i)] for i in sorted(k for (f, k) in rows if f == fname)]
    total = len(rows_list)
    path = ROOT / fname
    t = path.read_text(encoding="utf-8")
    tables = [m for m in re.finditer(r"<table>[\s\S]*?</table>", t) if "<th>出处</th>" in m.group(0)]
    counts = [len(re.findall(r"<tr>\s*<td>", m.group(0))) for m in tables]
    assert sum(counts) == total, f"{fname}: 表格行总数 {sum(counts)} != 预期 {total}"
    done = 0
    for ti in range(len(tables) - 1, -1, -1):
        tm = tables[ti]
        table = tm.group(0)
        body_rows = list(re.finditer(r"<tr>\s*<td>[\s\S]*?</tr>", table))
        base = sum(counts[:ti])  # 此表之前各表的行数 → 文件内行序基数
        work = table  # 行替换在原表字符串上进行，位置才与 body_rows 一致
        assert len(body_rows) == counts[ti]
        for ridx in range(len(body_rows) - 1, -1, -1):
            rm = body_rows[ridx]
            cells = [re.sub(r"^<td>|</td>$", "", x) for x in re.findall(r"<td>[\s\S]*?</td>", rm.group(0))]
            q = rows_list[base + ridx]
            assert strip_tags(cells[-1]) == q["cite"], f"{fname} 行{base + ridx + 1}: 出处不一致 {strip_tags(cells[-1])!r} != {q['cite']!r}"
            first = cells[0] + pop_html(q["cite"], q.get("quote"), q.get("page"))
            new_row = "<tr class=\"a-row\" tabindex=\"0\">\n" + "".join(
                f"<td>{c}</td>\n" for c in [first] + cells[1:-1]) + "</tr>"
            work = work[:rm.start()] + new_row + work[rm.end():]
            done += 1
        new_table = work.replace("<th>出处</th>", "")
        t = t[:tm.start()] + new_table + t[tm.end():]
    old, new = INTRO_REPLACEMENTS[fname]
    assert old in t, f"{fname}: 导语未找到"
    t = t.replace(old, new)
    assert OLD_CSS in t and OLD_JS in t, f"{fname}: 旧 CSS/JS 未找到"
    t = t.replace(OLD_CSS, NEW_CSS)
    t = t.replace(OLD_JS, OLD_JS.replace("querySelectorAll('.a')", "querySelectorAll('.a, .a-row')"))
    if not dry:
        path.write_text(t, encoding="utf-8")
    return done


def main():
    dry = "--dry-run" in sys.argv
    dumps = {p.stem: p.read_text(encoding="utf-8") for p in TXT.glob("手册*.txt")}
    rows = load_rows()
    print("table rows loaded:", len(rows))
    bad = validate(rows, dumps)
    if bad:
        print("VALIDATION FAILURES:")
        for b in bad:
            print("  ", b)
        sys.exit(1)
    print("validation ok: 每条表格行引文均为对应手册文本的逐字子串")
    for f in FILES:
        n = transform_file(f, rows, dry)
        print(f"{f}: {n} 行已处理")
    if not dry:
        for f in FILES:
            assert "<th>出处</th>" not in (ROOT / f).read_text(encoding="utf-8"), f"{f}: 仍有出处列"
    print("done", "(dry-run)" if dry else "(written)")


if __name__ == "__main__":
    main()
