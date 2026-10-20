# -*- coding: utf-8 -*-
"""下载中国人民银行《中国货币政策执行报告》各期 PDF。

数据来源：央行官网货币政策司"货币政策执行报告"栏目（单页列出 2001Q1 至最新各期）。
用法: python -X utf8 src/download_mpr.py
可重复运行：已存在且校验通过（%PDF 文件头）的文件跳过。
输出: 《中国货币政策执行报告》/YYYYQn_中国货币政策执行报告.pdf + source_index.csv
"""
import csv
import datetime
import os
import re
import subprocess
import sys
import time

BASE = "https://www.pbc.gov.cn"
LIST_URL = BASE + "/zhengcehuobisi/125207/125227/125957/index.html"
OUT_DIR = "《中国货币政策执行报告》"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
QUARTERS = {"一": "Q1", "二": "Q2", "三": "Q3", "四": "Q4"}
NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def fetch(url, retries=3):
    """经 curl 抓取，返回原始字节：Python 原生 TLS 握手会被官网防护重置，curl 可正常访问。"""
    last = None
    for i in range(retries):
        p = subprocess.run(
            ["curl", "-sS", "--fail", "-L", "--max-time", "90",
             "-A", UA, "-e", BASE + "/", url],
            capture_output=True)
        if p.returncode == 0:
            return p.stdout
        last = p.stderr.decode("utf-8", "replace").strip()
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url} 失败: {last}")


def absurl(u):
    return u if u.startswith("http") else BASE + u


def parse_list():
    html = fetch(LIST_URL).decode("utf-8", "replace")
    items, seen = [], set()
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        t = re.sub(r"<[^>]+>", "", text).strip()
        m = re.match(r"(\d{4})年第([一二三四])季度中国货币政策执行报告$", t)
        if m and href not in seen:
            seen.add(href)
            items.append({
                "year": int(m.group(1)),
                "q": QUARTERS[m.group(2)],
                "title": t,
                "article_url": absurl(href),
            })
    items.sort(key=lambda x: (x["year"], x["q"]))
    return items


def article_pdfs(url):
    html = fetch(url).decode("utf-8", "replace")
    meta = re.search(r'<meta\s+name="createDate"\s+content="([^"]+)"', html)
    created = meta.group(1).strip() if meta else ""
    pdfs = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if href.lower().endswith(".pdf"):
            t = re.sub(r"<[^>]+>", "", text).strip()
            pdfs.append((absurl(href), t))
    if not pdfs:  # 兜底：页面任意 .pdf 链接
        for href in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
            pdfs.append((absurl(href), ""))
    return created, pdfs


def valid_pdf(path):
    try:
        if os.path.getsize(path) < 50_000:
            return False
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    items = parse_list()
    print(f"列表解析到 {len(items)} 期报告", flush=True)
    rows, failures = [], []
    for n, it in enumerate(items, 1):
        tag = f'{it["year"]}{it["q"]}'
        try:
            created, pdfs = article_pdfs(it["article_url"])
        except Exception as e:
            failures.append((tag, f"文章页抓取失败: {e}"))
            print(f"[{n}/{len(items)}] {tag} 文章页失败: {e}", flush=True)
            continue
        if not pdfs:
            failures.append((tag, "页面未找到 PDF 附件"))
            print(f"[{n}/{len(items)}] {tag} 无 PDF 链接", flush=True)
            continue
        for pi, (pdf_url, orig_name) in enumerate(pdfs, 1):
            orig_name = orig_name or os.path.basename(pdf_url)
            if len(pdfs) == 1:
                fname = f"{tag}_中国货币政策执行报告.pdf"
            else:
                fname = f"{tag}_附件{pi}_{orig_name}"
            fpath = os.path.join(OUT_DIR, fname)
            status = "跳过（已存在）"
            if not valid_pdf(fpath):
                try:
                    data = fetch(pdf_url)
                except Exception as e:
                    failures.append((tag, f"PDF 下载失败: {e}"))
                    print(f"[{n}/{len(items)}] {tag} PDF 失败: {e}", flush=True)
                    continue
                if data[:5] != b"%PDF-":
                    failures.append((tag, "下载内容非 PDF"))
                    continue
                with open(fpath, "wb") as f:
                    f.write(data)
                status = "本次下载"
            size = os.path.getsize(fpath)
            rows.append({
                "source_id": f"S{n:03d}",
                "quarter": tag,
                "title": it["title"],
                "publisher": "中国人民银行",
                "source_type": "官方",
                "article_url": it["article_url"],
                "pdf_url": pdf_url,
                "published_at": created or "未注明",
                "accessed_at": NOW,
                "original_filename": orig_name,
                "local_path": f"{OUT_DIR}/{fname}",
                "size_bytes": size,
                "verify_status": "已校验%PDF文件头",
                "limitations": "多附件" if len(pdfs) > 1 else "",
            })
            print(f"[{n}/{len(items)}] {tag} {status} {size/1e6:.1f}MB", flush=True)
        time.sleep(0.3)
    csv_path = os.path.join(OUT_DIR, "source_index.csv")
    fields = ["source_id", "quarter", "title", "publisher", "source_type",
              "article_url", "pdf_url", "published_at", "accessed_at",
              "original_filename", "local_path", "size_bytes",
              "verify_status", "limitations"]
    # 多附件时按报告去重编号：主报告行号沿用期号
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(sorted(rows, key=lambda x: (x["quarter"], x["source_id"][-3:])), 1):
            r = dict(r)
            if r["limitations"]:
                r["source_id"] = f"{r['source_id']}.{i}"
            w.writerow(r)
    print(f"\n索引已写入 {csv_path}，共 {len(rows)} 个文件记录", flush=True)
    if failures:
        print("失败清单：", flush=True)
        for tag, msg in failures:
            print(f"  {tag}: {msg}", flush=True)
        sys.exit(1)
    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
