# -*- coding: utf-8 -*-
"""核验 site/ 三个 HTML 中批注气泡的摘录是否为对应来源的逐字子串。

蓝色批注（.a.upd 内的 .pop）：来源为央行专栏 md 提取件，逐字精确比对：
  <span class="src">央行更新：2024Q4 货政报告·专栏 1《……》</span>
绿色批注（.a.grn 内的 .pop）：来源为寇文红博士文章 PDF 提取件（sources/txt/，仅本地留存），
PDF 提取文本在数字与标点前后带有空格，故按"删除全部空白后"比对：
  <span class="src">观点补充：寇文红博士《……》</span>
一个 pop 可含多个 src 段；每个 q 归属于其前方最近的 src。
用法：python -X utf8 src/verify_update_quotes.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS = ROOT / "sources" / "monetary_policy_report" / "columns"
KOU_TXT = ROOT / "sources" / "txt" / "2024年6月以来我国央行对利率体系和调控框架的改革.txt"
PAGES = ["site/framework.html", "site/evolution.html", "site/stages.html"]

SRC_RE = re.compile(r'<span class="src">央行更新：(\d{4})Q([1-4]) 货政报告·专栏 (\d+)《')
KOU_RE = re.compile(r'<span class="src">观点补充：寇文红博士')
# q 段落以 ”</span> 收尾；摘录内部的嵌套弯引号后不会紧跟 </span>，故该终止符无歧义
Q_RE = re.compile(r'<span class="q">“(.*?)”</span>', re.S)


def kou_text() -> str:
    return KOU_TXT.read_text(encoding="utf-8")


def col_text(issue: str, no: str) -> str:
    hits = sorted(COLS.glob(f"{issue}_专栏{no}_*.md"))
    if not hits:
        raise FileNotFoundError(f"未找到专栏文件：{issue} 专栏{no}")
    return hits[0].read_text(encoding="utf-8")


def extract_pops(html: str) -> list:
    """按 span 嵌套深度扫描，提取每个 .pop 的完整内容（兼容有/无换行的各种书写格式）。"""
    pops, i, OPEN = [], 0, '<span class="pop">'
    while True:
        j = html.find(OPEN, i)
        if j < 0:
            return pops
        k = j + len(OPEN)
        depth = 1
        while k < len(html) and depth:
            m = re.match(r'<span\b|</span>', html[k:])
            if m:
                depth += -1 if m.group(0) == "</span>" else 1
                k += m.end()
            else:
                k += 1
        pops.append(html[j + len(OPEN): k - len("</span>")])
        i = k


def main() -> int:
    total = ok = 0
    fail = []
    for page in PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        # 逐个 pop 检查
        pops = extract_pops(html)
        checked_in_page = 0
        for pop in pops:
            if "央行更新" not in pop and "寇文红博士" not in pop:
                continue
            # 按 src 分段，确定每段 q 的归属
            parts = re.split(r'(<span class="src">[^<]*</span>)', pop)
            cur_key = None
            for part in parts:
                m = SRC_RE.search(part)
                if m:
                    cur_key = (m.group(1) + "Q" + m.group(2), m.group(3))
                    continue
                if KOU_RE.search(part):
                    cur_key = "KOU"
                    continue
                if cur_key is None:
                    continue
                if cur_key == "KOU":
                    text = re.sub(r"\s+", "", kou_text())
                    quotes = [re.sub(r"\s+", "", q) for q in Q_RE.findall(part)]
                else:
                    text = col_text(*cur_key)
                    quotes = Q_RE.findall(part)
                for quote in quotes:
                    total += 1
                    checked_in_page += 1
                    if quote in text:
                        ok += 1
                    else:
                        fail.append((page, cur_key, quote[:60]))
        print(f"{page}: 政策更新摘录 {checked_in_page} 条")

    print(f"\n合计 {total} 条摘录，逐字命中 {ok} 条，失败 {len(fail)} 条")
    for page, key, head in fail:
        print(f"  [FAIL] {page} {key}: {head}…")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
