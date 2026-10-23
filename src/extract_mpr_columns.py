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
输出: sources/monetary_policy_report/columns/YYYYQn_专栏N_标题.md + 专栏文章_index.csv
（2026-10-23 起档案移入 sources/：sources/monetary_policy_report/columns|columns_pdf，PDF 与 md 文件名仍为中文。）
"""
import csv
import glob
import os
import re
import sys
import time

import pymupdf

REPORT_DIR = os.path.join("sources", "monetary_policy_report")
OUT_SUB = "columns"
PDF_SUB = "columns_pdf"
IDX_NAME = "专栏文章_index.csv"  # 索引文件名沿用中文：2026-10-23 仅文件夹改英文名，文件名不变
# 人工补录：文本模式下版式无法判定、需按原件补入的段落（键为 (期次, 专栏号)）。
# 2003Q2 专栏4 曾在此补录"三、中国债券市场展望"，收束规则改进后可自然完整
# 提取，已移除；如日后发现新的截断案例，在此登记补录文本。
SUPPLEMENTS = {}
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
            x0, y0, x1, y1 = l["bbox"]
            rows.append({"y": y0, "x0": x0, "x1": x1, "y1": y1,
                         "w": page.rect.width, "size": size,
                         "text": text, "mode": mode})
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


def looks_like_maintext(r, col_size):
    """全宽、字号不小于专栏正文的 0.93 倍、起印于版心左缘 => 主文段落行。
    图表标签（短）、表格单元格（短/小字）、脚注（小字）、缩进的栏内内容均排除。"""
    return ((r["x1"] - r["x0"]) > 0.5 * r["w"]
            and r["size"] >= col_size * 0.93
            and r["x0"] < 0.17 * r["w"])


def next_page_continues(pages, p, colfont, col_size):
    """按顺序扫描次页，判断本文是否跨页继续：先遇到本文楷体行 => 继续；
    先遇到主文段落行或下一篇专栏标题 => 止于本页。
    次页开头的图表残行（短小、非专栏字体）不影响判断。"""
    if p + 1 >= len(pages):
        return False
    seen = 0
    for r in pages[p + 1]:
        t = r["text"].strip()
        if not t or is_pagenum(t):
            continue
        seen += 1
        if seen > 40:
            break
        if HEADING.match(t) and not is_toc_line(t):
            return False
        if r["mode"] == colfont:
            return True
        if looks_like_maintext(r, col_size):
            return False
    return False


def column_end(pages, pno, li, colfont, col_size, main_sec=0):
    """从标题行下一行起扫描，返回 (end_pno, end_li)：专栏正文结束位置（不含）。

    字体模式（colfont != 'body'）：专栏内图表混入主文字体行不中断；主文节标题
    （第X部分/一、）字号明显大于专栏正文（如 15pt 对 12pt）时收束；非专栏字体
    行之后、下一个专栏标题之前若无专栏字体行，即主文恢复，就地收束——同页后
    文中下一篇专栏的楷体不作为本文延续；最后才考虑"次页开头是否有专栏字体"
    的跨页继续。文本模式（colfont == 'body'，2002—2003 年宋体版式）：专栏
    内部小标题与主文节标题完全无版式差别；收束于下一个专栏标题（或"第X部分"）
    之前、编号为 main_sec+1 的最后一个节标题行——专栏内部小标题从一重新编号，
    与主文节号撞车时主文必然重复出现同号，取最后一个。"""
    p, i = pno, li + 1
    if colfont == "body":
        end = None
        while p < len(pages):
            lines = pages[p]
            while i < len(lines):
                t = lines[i]["text"].strip()
                if not t or is_pagenum(t):
                    i += 1
                    continue
                m = HEADING.match(t)
                if (m and not is_toc_line(t)) or (t.startswith("第") and "部分" in t[:6]):
                    return end if end else (p, i)
                ms = SEC_NUM.match(t)
                if ms and cn_int(ms.group(1)) == main_sec + 1:
                    end = (p, i)
                i += 1
            p += 1
            i = 0
        return end if end else (len(pages) - 1, len(pages[-1]))
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
            if r["mode"] == colfont:
                i += 1
                continue
            if r["mode"] != colfont and looks_like_maintext(r, col_size):
                return p, i  # 主文段落行（全宽、主文字号、版心左缘）：专栏已结束
            if SECTION.match(t) and r["size"] > col_size * 1.12:
                return p, i
            # 向后看本页：以下一个专栏标题为界（标题后属于下一篇）
            nxt = len(lines)
            for j in range(i + 1, len(lines)):
                if HEADING.match(lines[j]["text"]) and not is_toc_line(lines[j]["text"]):
                    nxt = j
                    break
            gap = lines[i + 1:nxt]
            if any(x["mode"] == colfont and not HEADING.match(x["text"]) for x in gap):
                i += 1  # 本页其后仍是本文内容（图表行等），跳过继续
                continue
            if next_page_continues(pages, p, colfont, col_size):
                break  # 跳出内层循环，由外层翻页并重取行列表
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
    """标题行之后若干实质行的主导中文字体类别及其字号，作为专栏正文字体。"""
    counts, sizes = {}, {}
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
        sizes[r["mode"]] = sizes.get(r["mode"], 0) + r["size"] * n
    if not counts or max(counts, key=counts.get) == "other":
        return "kai", 12.0
    mode = max(counts, key=counts.get)
    return mode, sizes[mode] / counts[mode]


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


def column_pdf(src_path, out_path, pages, pno, li, ep, ei):
    """把专栏所在页面裁剪成独立 PDF：首页裁去专栏上方主文，末页裁去下方主文，
    中间页整页保留；图表、表格随原版面完整保留。裁剪线取专栏边界行与相邻
    主文行的几何中点，避免残留半行文字。"""
    src = pymupdf.open(src_path)
    out = pymupdf.open()
    out.insert_pdf(src, from_page=pno, to_page=ep)
    head = pages[pno][li]
    start_lines = pages[pno]
    if li > 0:
        top = max((start_lines[li - 1]["y1"] + head["y"]) / 2, 0)
    else:
        top = max(head["y"] - 14, 0)
    if ei > 0:
        last = pages[ep][ei - 1]
        end_lines = pages[ep]
        bottom = last["y1"] + 10
        if ei < len(end_lines):  # 与下方主文行保持距离
            bottom = min(bottom + 2, (last["y1"] + end_lines[ei]["y"]) / 2 + 4)
    else:
        last = pages[ep - 1][-1]
        bottom = min(last["y1"] + 10, src[ep].rect.height)
    bottom = min(bottom, src[ep].rect.height)
    width = src[pno].rect.width
    if pno == ep:
        out[0].set_cropbox(pymupdf.Rect(0, top, width, bottom))
    else:
        out[0].set_cropbox(pymupdf.Rect(0, top, width, src[pno].rect.height))
        out[-1].set_cropbox(pymupdf.Rect(0, 0, width, bottom))
    for k in range(3):  # Windows 下目标文件可能被查看器/杀毒/索引器锁定
        try:
            out.ez_save(out_path)
            out.close()
            src.close()
            return True
        except Exception:
            time.sleep(1.5)
    out.close()
    src.close()
    return False


def main():
    dry = "--dry-run" in sys.argv
    pdf_dir = os.path.join(REPORT_DIR, PDF_SUB)
    pdfs = sorted(glob.glob(os.path.join(REPORT_DIR, "*Q*_中国货币政策执行报告.pdf")))
    if not dry:
        os.makedirs(os.path.join(REPORT_DIR, OUT_SUB), exist_ok=True)
        os.makedirs(pdf_dir, exist_ok=True)
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
            colfont, col_size = detect_colfont(pages, pno, li)
            ep, ei = column_end(pages, pno, li, colfont, col_size, sec_no)
            if ei == 0 and ep > pno:
                # 主文在次页页首恢复：专栏止于上一页底，PDF 页范围回收一页
                ep, ei = ep - 1, len(pages[ep - 1])
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
            supp = SUPPLEMENTS.get((tag, num))
            note = supp["note"] if supp else None
            paras2 = paras + (supp["paras"] if supp else [])
            base = f"{tag}_专栏{num}_{safe_name(title)}"
            text = (
                f"# {title}\n\n"
                f"> 摘自《中国货币政策执行报告》{tag} 专栏 {num}（PDF 第 {npage} 页）\n"
                f"> 原文全文（含图表）：../{PDF_SUB}/{base}.pdf\n"
                f"> 自动按原件版式提取，正文未改写；图表数据以 PDF 原件为准。\n"
                + (f"> {note}\n" if note else "")
                + "\n" + "\n\n".join(paras2) + "\n"
            )
            with open(os.path.join(REPORT_DIR, OUT_SUB, base + ".md"), "w", encoding="utf-8") as f:
                f.write(text)
            if not column_pdf(pdf, os.path.join(pdf_dir, base + ".pdf"), pages, pno, li, ep, ei):
                notes.append(f"{tag} 专栏{num}: PDF 被其他程序占用，未能更新（关闭查看器后重跑可补）")
            rows.append({
                "issue": tag, "column_no": num, "title": title,
                "pdf_pages": npage, "chars": sum(len(p) for p in paras2),
                "file": base + ".md", "pdf_file": base + ".pdf",
            })
        print(f"{tag}: {len(heads)} 篇专栏")
    if not dry:
        idx = os.path.join(REPORT_DIR, IDX_NAME)
        with open(idx, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["issue", "column_no", "title", "pdf_pages", "chars", "file", "pdf_file"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n索引已写入 {idx}，共 {len(rows)} 篇")
    if notes:
        print("\n需注意：")
        for n in notes:
            print(" ", n)


if __name__ == "__main__":
    main()
