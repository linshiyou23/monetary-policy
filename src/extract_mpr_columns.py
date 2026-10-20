# -*- coding: utf-8 -*-
"""从《中国货币政策执行报告》各期 PDF 中提取专栏（科普/教学性文章）。

版式与切分规则（经 2001—2026 各期抽查确认）：
- 每篇专栏以"专栏 N 标题"独立标题行开始；目录页（同页多个标题行或带点线）
  只用于补全标题，不作为正文起点。
- 2004 年起专栏正文用楷体排版（主文为仿宋/宋体、图表混排仿宋宋体黑体），
  按字体游走切分：标题后主体的主导字体即专栏字体，其后同页或次页仍有该字体
  则继续，直到主文恢复。
- 2002—2003 年专栏与主文同为宋体，无法按字体区分，按"下一个专栏标题或
  '第X部分/一、'节标题行"收束；栏目若紧接主文段落，可能多收少量尾文。
- 2001 年各期及 2002 年前两期无专栏。

用法:
  python -X utf8 src/extract_mpr_columns.py --dry-run   # 仅检测并打印各期专栏
  python -X utf8 src/extract_mpr_columns.py             # 写出 Markdown 与索引
输出: 中国货币政策执行报告/专栏文章/YYYYQn_专栏N_标题.md + 专栏文章_index.csv
"""
import csv
import glob
import os
import re
import sys

import pymupdf

REPORT_DIR = "中国货币政策执行报告"
OUT_SUB = "专栏文章"
HEADING = re.compile(r"^专\s*栏\s*([0-9０-９一二三四五六七八九十]+)\s*[:：、]?\s*(.*)$")
LEADER = re.compile(r"\.{4,}|…+")
CN_NUM = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
          "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
SECTION = re.compile(r"^第[一二三四五六七八]+部分|^[一二三四五六七八九十]+、")
SEC_NUM = re.compile(r"^([一二三四五六七八九十]+)、")


def cn_int(s):
    """中文小写数字转整数（节标题编号，最大到两位）。"""
    d = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
         "八": 8, "九": 9, "十": 10}
    if s in d:
        return d[s]
    if "十" in s:
        a, _, b = s.partition("十")
        return (d.get(a, 1) if a else 1) * 10 + d.get(b, 0)
    return 0


def norm_font(name):
    """修正 PDF 内嵌字体名乱码：2019 年前后为 UTF-8 字节被当 Latin-1（如
    æ¥·ä½\x93 -> 楷体），2008 年前后为 GBK 字节被当 Latin-1（如 ¿¬Ìå -> 楷体）。"""
    if all(ord(c) < 128 for c in name):
        return name
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def fclass(name):
    n = norm_font(name)
    if "楷" in n or "KaiTi" in n:
        return "kai"
    if "黑" in n or "SimHei" in n:
        return "hei"
    if "仿" in n or "宋" in n or "FangSong" in n or "SimSun" in n:
        return "body"
    return "other"


def page_lines(page):
    """按阅读顺序返回页面文本行：dict(y, x0, size, text, mode)。mode 取行内
    中文字符的主导字体类别；无中文行记为 other。"""
    rows = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            counts, size = {}, 0.0
            cjk = 0
            for s in spans:
                k = fclass(s["font"])
                n = sum(1 for ch in s["text"] if "\u4e00" <= ch <= "\u9fff")
                counts[k] = counts.get(k, 0) + n
                cjk += n
                size = max(size, s["size"])
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            mode = max(counts, key=counts.get) if cjk else "other"
            x0, y0 = l["bbox"][0], l["bbox"][1]
            rows.append({"y": y0, "x0": x0, "size": size, "text": text, "mode": mode})
    rows.sort(key=lambda r: (round(r["y"], 1), r["x0"]))
    return rows


def is_toc_line(text):
    return bool(LEADER.search(text))


def is_pagenum(text):
    return bool(re.fullmatch(r"\d{1,3}", text.strip()))


def clean_title(t):
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[.．…]{2,}[0-9０-９]{0,3}$", "", t)  # 去掉目录点线和页码残留
    return t.strip("。：: 、.……")


def norm_num(s):
    s = s.strip()
    return CN_NUM.get(s, s.translate(str.maketrans("０１２３４５６７８９", "0123456789")))


def scan_issue(pdf_path):
    """返回 (toc_titles, headings, pages)，页码一律为 0 基。
    目录页判定：同页出现 >=3 个专栏标题行，或标题行带点线引导符。"""
    doc = pymupdf.open(pdf_path)
    toc_titles, headings, pages = [], [], []
    for pno, page in enumerate(doc):
        lines = page_lines(page)
        pages.append(lines)
        matches = [(li, HEADING.match(r["text"])) for li, r in enumerate(lines)
                   if HEADING.match(r["text"])]
        n_leader = sum(1 for li, _ in matches if is_toc_line(lines[li]["text"]))
        is_toc_page = len(matches) >= 3 or n_leader >= 1
        for li, m in matches:
            num = norm_num(m.group(1))
            if not is_toc_page:
                headings.append([pno, li, num, m.group(2).strip()])
                continue
            raw = m.group(2)
            title = clean_title(LEADER.split(raw)[0]) if is_toc_line(raw) else clean_title(raw)
            if len(title) < 2:  # 新式目录：标题在下一行（带点线和页码）
                for r2 in lines[li + 1:li + 3]:
                    if LEADER.search(r2["text"]):
                        title = clean_title(LEADER.split(r2["text"])[0])
                        break
            if title:
                toc_titles.append((num, title))
    return toc_titles, headings, pages


def has_body_heading(lines):
    return any(HEADING.match(r["text"]) and not is_toc_line(r["text"]) for r in lines)


def next_page_continues(pages, p, colfont):
    """下一页开头若干实质行是否仍为专栏字体（跨页继续），或下一页有新专栏标题。"""
    if p + 1 >= len(pages):
        return False
    seen = 0
    for r in pages[p + 1]:
        t = r["text"].strip()
        if not t or is_pagenum(t):
            continue
        seen += 1
        if seen > 6:
            break
        if r["mode"] == colfont or (HEADING.match(t) and not is_toc_line(t)):
            return True
    return False


def column_end(pages, pno, li, colfont, main_sec=0):
    """从标题行下一行起扫描，返回 (end_pno, end_li)：专栏正文结束位置（不含）。

    字体模式（colfont != 'body'）：专栏内图表混入主文字体行不中断；仅当其后
    同页无专栏字体、且下一页开头也不是专栏字体（主文确已恢复）时收束。
    文本模式（colfont == 'body'，2002—2003 年宋体版式）：专栏内部也可能有
    "一、二、"小标题，与主文节标题无字体差别，故收束于编号为 main_sec+1 的
    节标题（主文节号接续）或"第X部分"行；编号不接续的视为专栏内部小标题。"""
    p, i = pno, li + 1
    textmode = colfont == "body"
    while p < len(pages):
        lines = pages[p]
        while i < len(lines):
            r = lines[i]
            t = r["text"].strip()
            if not t or is_pagenum(t):
                i += 1
                continue
            m = HEADING.match(t)
            if m and not is_toc_line(t):
                return p, i
            if textmode:
                if t.startswith("第") and "部分" in t[:6]:
                    return p, i
                ms = SEC_NUM.match(t)
                if ms and cn_int(ms.group(1)) == main_sec + 1:
                    return p, i
                i += 1
                continue
            if r["mode"] == colfont:
                i += 1
                continue
            if any(x["mode"] == colfont and not HEADING.match(x["text"])
                   for x in lines[i + 1:]):
                i += 1
                continue
            if next_page_continues(pages, p, colfont):
                p, i = p + 1, 0
                continue
            return p, i
        p += 1
        i = 0
    return len(pages) - 1, len(pages[-1])


def scan_gap(pages, start_pos, end_pos):
    """区间 (pno, li) 含起点、不含终点内最后一个主文节标题编号；遇"第X部分"归 0。
    用于推断专栏开始时主文节号，供文本模式判断节标题接续。"""
    n = 0
    (sp, si), (ep, ei) = start_pos, end_pos
    p, i = sp, si
    while p < ep or (p == ep and i < ei):
        if p >= len(pages):
            break
        lines = pages[p]
        lim = ei if p == ep else len(lines)
        while i < lim:
            t = lines[i]["text"].strip()
            if t.startswith("第") and "部分" in t[:6]:
                n = 0
            else:
                ms = SEC_NUM.match(t)
                if ms:
                    n = cn_int(ms.group(1))
            i += 1
        p += 1
        i = 0
    return n


def detect_colfont(pages, pno, li):
    """标题行之后若干实质行的主导中文字体类别，作为专栏正文字体。"""
    counts = {}
    seen = 0
    for r in pages[pno][li + 1:]:
        t = r["text"].strip()
        if not t or is_pagenum(t):
            continue
        seen += 1
        if seen > 12:
            break
        n = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        counts[r["mode"]] = counts.get(r["mode"], 0) + n
    if not counts or max(counts, key=counts.get) == "other":
        return "kai"
    return max(counts, key=counts.get)


def reflow(lines):
    """把专栏正文行合并为段落：按行首缩进（相对左边距约两个字符）分段。"""
    paras, cur = [], ""
    base_x = min((r["x0"] for r in lines), default=0)
    for r in lines:
        t = re.sub(r"\s+", "", r["text"])
        if not t or is_pagenum(t):
            continue
        indent = r["x0"] - base_x > max(r["size"], 8) * 1.5
        if indent and cur:
            paras.append(cur)
            cur = t
        else:
            cur += t
    if cur:
        paras.append(cur)
    return paras


def safe_name(title):
    t = re.sub(r'[\\/:*?"<>|]', "", title).strip(" .")
    return t[:60] if len(t) > 60 else t


def main():
    dry = "--dry-run" in sys.argv
    pdfs = sorted(glob.glob(os.path.join(REPORT_DIR, "*Q*_中国货币政策执行报告.pdf")))
    if not dry:
        os.makedirs(os.path.join(REPORT_DIR, OUT_SUB), exist_ok=True)
    rows, notes = [], []
    for pdf in pdfs:
        tag = os.path.basename(pdf).split("_")[0]
        toc, heads, pages = scan_issue(pdf)
        if not heads:
            notes.append(f"{tag}: 未检测到专栏（目录 {len(toc)} 条）")
            print(f"{tag}: 0 篇专栏")
            continue
        if len(heads) != len({(h[2]) for h in heads}) or len(heads) != len(toc):
            notes.append(f"{tag}: 正文专栏 {len(heads)} 篇 vs 目录 {len(toc)} 条")
        prev_end = (0, 0)
        for pno, li, num, title_raw in heads:
            sec_no = scan_gap(pages, prev_end, (pno, li))
            colfont = detect_colfont(pages, pno, li)
            ep, ei = column_end(pages, pno, li, colfont, sec_no)
            prev_end = (ep, ei)
            title = clean_title(title_raw)
            for tn, tt in toc:  # 目录标题优先：前缀一致（含少量断字）时取更全者
                if tn != num or not tt:
                    continue
                short, long_ = sorted([title, tt], key=len)
                if long_.startswith(short) or (
                        len(short) > 4 and long_[:len(short) - 1] == short[:len(short) - 1]
                        and len(long_) <= len(short) + 2):
                    if len(tt) > len(title):
                        title = tt
                    break
            body_lines = []
            for p in range(pno, ep + 1):
                ls = pages[p]
                a = li + 1 if p == pno else 0
                b = ei if p == ep else len(ls)
                body_lines.extend(ls[a:b])
            if colfont != "body":
                while body_lines and body_lines[-1]["mode"] != colfont:
                    body_lines.pop()  # 去掉专栏末尾混入的图表/主文残行
            paras = reflow(body_lines)
            npage = f"{pno + 1}" if ep == pno else f"{pno + 1}—{ep + 1}"
            chars = sum(len(p) for p in paras)
            if dry:
                print(f"    专栏{num} [{npage}页|{colfont}] {title} ({chars}字)")
                continue
            fname = f"{tag}_专栏{num}_{safe_name(title)}.md"
            text = (
                f"# {title}\n\n"
                f"> 摘自《中国货币政策执行报告》{tag} 专栏 {num}（PDF 第 {npage} 页）\n"
                f"> 自动按原件版式提取，正文未改写；图表内容以原件为准。\n\n"
                + "\n\n".join(paras)
                + "\n"
            )
            with open(os.path.join(REPORT_DIR, OUT_SUB, fname), "w", encoding="utf-8") as f:
                f.write(text)
            rows.append({
                "issue": tag, "column_no": num, "title": title,
                "pdf_pages": npage, "chars": chars, "file": fname,
            })
        print(f"{tag}: {len(heads)} 篇专栏")
    if not dry:
        idx = os.path.join(REPORT_DIR, f"{OUT_SUB}_index.csv")
        with open(idx, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["issue", "column_no", "title", "pdf_pages", "chars", "file"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n索引已写入 {idx}，共 {len(rows)} 篇")
    if notes:
        print("\n需注意：")
        for n in notes:
            print(" ", n)


if __name__ == "__main__":
    main()
