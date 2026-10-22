# -*- coding: utf-8 -*-
"""核验 site/ 三个 HTML 中"政策更新"气泡的专栏摘录是否为专栏文章 md 的逐字子串。

气泡格式约定（.a.upd 内的 .pop）：
  <span class="src">央行更新：2024Q4 货政报告·专栏 1《……》</span>
  <span class="q">“……摘录……”</span>
一个 pop 可含多个 src 段；每个 q 归属于其前方最近的 src。
用法：python -X utf8 src/verify_update_quotes.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS = ROOT / "中国货币政策执行报告" / "专栏文章"
PAGES = ["site/framework.html", "site/evolution.html", "site/stages.html"]

SRC_RE = re.compile(r'<span class="src">央行更新：(\d{4})Q([1-4]) 货政报告·专栏 (\d+)《')
# q 段落以 ”</span> 收尾；摘录内部的嵌套弯引号后不会紧跟 </span>，故该终止符无歧义
Q_RE = re.compile(r'<span class="q">“(.*?)”</span>', re.S)


def col_text(issue: str, no: str) -> str:
    hits = sorted(COLS.glob(f"{issue}_专栏{no}_*.md"))
    if not hits:
        raise FileNotFoundError(f"未找到专栏文件：{issue} 专栏{no}")
    return hits[0].read_text(encoding="utf-8")


def main() -> int:
    total = ok = 0
    fail = []
    for page in PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        # 逐个 pop 检查
        pops = re.findall(r'<span class="pop">(.*?)</span></span>', html, re.S)
        checked_in_page = 0
        for pop in pops:
            if "央行更新" not in pop:
                continue
            # 按 src 分段，确定每段 q 的归属
            parts = re.split(r'(<span class="src">央行更新：\d{4}Q[1-4] 货政报告·专栏 \d+《[^<]*</span>)', pop)
            cur_key = None
            for part in parts:
                m = SRC_RE.search(part)
                if m:
                    cur_key = (m.group(1) + "Q" + m.group(2), m.group(3))
                    continue
                if cur_key is None:
                    continue
                text = col_text(*cur_key)
                for quote in Q_RE.findall(part):
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
