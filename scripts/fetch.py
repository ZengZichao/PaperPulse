#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PaperPulse — 期刊文献日报抓取脚本

从 sources.json 配置的数据源抓取当日文献：
  1. RSS/Atom feeds (feedparser)
  2. PubMed E-utilities (esearch + esummary + efetch)

然后执行：去重、日期过滤、非文章过滤，最终输出 data/YYYY-MM-DD.json
供前端读取。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import feedparser
import requests

# ─── 路径常量 ───
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = PROJECT_ROOT / "config" / "sources.json"
DATA_DIR = PROJECT_ROOT / "data"
DAYS_BACK = int(os.getenv("DAYS_BACK", "3"))
USER_AGENT = "Mozilla/5.0 (PaperPulse Academic Research Bot)"
REQUEST_TIMEOUT = 30

# 日期文件名 pattern，例如 2026-11-14
_DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 北京时区（UTC+8）：所有日期计算均按北京时间，避免服务器 UTC 时区导致日期偏差
BJ_TZ = timezone(timedelta(hours=8))

# ─── 日期工具 ───

def local_ymd(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def get_accept_dates(days_back: int = DAYS_BACK) -> Set[str]:
    today = datetime.now(BJ_TZ)
    dates = set()
    for i in range(days_back):
        d = today - timedelta(days=i)
        dates.add(local_ymd(d))
    return dates

def get_primary_date() -> str:
    return local_ymd(datetime.now(BJ_TZ))

def parse_date(raw: str) -> Optional[str]:
    """尝试多种格式解析日期，返回 YYYY-MM-DD 或 None。"""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    # ISO 8601
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S", "%d %b %Y",
        "%Y %b %d", "%Y %b",
    ]:
        try:
            dt = datetime.strptime(s[:len(s)], fmt)
            if dt.year < 1900:
                continue
            return local_ymd(dt)
        except ValueError:
            continue
    # 尝试 feedparser 的 time.struct_time
    return None

def parse_pubmed_date(raw: str) -> Optional[str]:
    """解析 PubMed 日期格式如 '2024 Jan 15', '2024 Jan'。"""
    if not raw:
        return None
    s = raw.strip()
    for fmt in ["%Y %b %d", "%Y %b"]:
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y %b":
                return None  # 只有年月，无法确定日
            return local_ymd(dt)
        except ValueError:
            continue
    return parse_date(s)

# ─── HTML 清理 ───

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

def strip_html(text: str) -> str:
    if not text:
        return ""
    s = unescape(text)
    s = _TAG_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()

# ─── 非文章过滤 ───

SKIP_PATTERNS = {
    "copyright", "editorial", "table of contents", "issue information",
    "this issue", "in this issue", "foreword", "preface",
    "acknowledgements", "correction", "erratum", "retraction", "book review",
}

def is_real_article(title: str) -> bool:
    if not title:
        return False
    t = title.strip().lower()
    if not t:
        return False
    return t not in SKIP_PATTERNS

# ─── Article 数据模型 ───

def make_article(
    title: str, link: str, pub_date: Optional[str], authors: List[str],
    doi: Optional[str], journal: str, source: str, pmid: Optional[str] = None,
    article_type: Optional[str] = None, abstract: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "title": title,
        "link": link,
        "pub_date": pub_date,
        "authors": authors,
        "doi": doi,
        "journal": journal,
        "source": source,
        "pmid": pmid,
        "translation": None,
        "article_type": article_type,
        "abstract": abstract,
    }

def article_id(a: Dict[str, Any]) -> str:
    return f"{a['journal']}|{a['source']}|{a.get('pmid') or ''}|{a['link']}|{a['title']}"


def article_keys(a: Dict[str, Any]) -> Set[str]:
    """跨来源去重键：DOI + 刊名/标题。
    RSS 与 PubMed 对同一篇文章给出的链接不同，只按 article_id 会重复收录。"""
    keys: Set[str] = set()
    doi = (a.get("doi") or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    if doi:
        keys.add("doi:" + doi)
    title = re.sub(r"[^a-z0-9]+", "", (a.get("title") or "").lower())
    if title:
        journal_key = normalize_journal_name(a.get("journal", ""))
        if journal_key.startswith("the "):
            journal_key = journal_key[4:]
        keys.add("title:" + journal_key + "|" + title)
    return keys

# ─── RSS 抓取 ───

TYPE_KEYWORDS = [
    ("review", "Review"), ("perspective", "Perspective"),
    ("editorial", "Editorial"), ("commentary", "Commentary"),
    ("comment", "Comment"), ("letter", "Letter"),
    ("correspondence", "Correspondence"),
    ("brief communication", "Brief Communication"),
    ("short communication", "Short Communication"),
    ("research article", "Research Article"),
    ("research", "Research Article"),
    ("original article", "Original Article"),
    ("original research", "Original Research"),
    ("article", "Article"),
    ("news & views", "News & Views"),
    ("news and views", "News & Views"),
    ("news", "News"), ("feature", "Feature"),
    ("protocol", "Protocol"), ("case report", "Case Report"),
    ("resource", "Resource"), ("analysis", "Analysis"),
    ("erratum", "Erratum"), ("correction", "Correction"),
    ("retraction", "Retraction"), ("preprint", "Preprint"),
    ("hypothesis", "Hypothesis"), ("methods", "Methods"),
    ("spotlight", "Spotlight"), ("preview", "Preview"),
    ("opinion", "Opinion"), ("viewpoint", "Viewpoint"),
    ("meeting report", "Meeting Report"),
    ("book review", "Book Review"),
]

TYPE_REGEXES = [(re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE), l) for p, l in TYPE_KEYWORDS]

def infer_type(categories: List[str]) -> Optional[str]:
    lowered = [c.lower() for c in categories]
    for regex, label in TYPE_REGEXES:
        for cat in lowered:
            if regex.search(cat):
                return label
    if len(categories) == 1 and categories[0]:
        return categories[0]
    return None

def fetch_rss(name: str, url: str, accept_dates: Set[str]) -> Tuple[List[Dict], Optional[str]]:
    """抓取并解析一个 RSS/Atom feed。返回 (articles, error)。"""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT},
                            allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "").lower()
        if content_type and "xml" not in content_type and "html" not in content_type:
            # 有些 feed 返回非标准 Content-Type 但内容是 XML
            if not resp.text.strip().startswith("<?xml") and "<rss" not in resp.text[:200] and "<feed" not in resp.text[:200]:
                return [], f"non-XML content-type: {content_type}"
    except Exception as e:
        return [], f"fetch error: {e}"

    parsed = feedparser.parse(resp.text)
    articles = []
    for entry in parsed.entries:
        title = strip_html(entry.get("title", ""))
        if not title:
            continue

        # 链接
        link = entry.get("link", "")

        # 日期
        # feedparser 会把命名空间字段转成下划线形式（dc:date -> dc_date），
        # ScienceDirect 等源只提供 dc:date，写 dc:date 会永远取不到日期。
        raw_date = (entry.get("published") or entry.get("updated") or
                    entry.get("dc_date") or entry.get("dc:date") or
                    entry.get("date") or "")
        item_date = parse_date(raw_date)

        # 保留：日期为空或在目标日期内
        if item_date and item_date not in accept_dates:
            continue

        # 作者
        authors = []
        if entry.get("authors"):
            authors = [strip_html(a.get("name", "")) for a in entry.authors if a.get("name")]
        elif entry.get("author"):
            authors = [strip_html(entry["author"])]

        # DOI
        doi = entry.get("doi") or entry.get("prism_doi") or entry.get("prism:doi") or ""
        if not doi:
            # 从 dc:identifier 或 guid 提取
            guid = entry.get("id", "") or entry.get("dc_identifier", "") or entry.get("dc:identifier", "")
            if guid.startswith("doi:"):
                guid = guid[4:]
            if guid.startswith("10."):
                doi = guid

        # 分类
        categories = []
        for tag in entry.get("tags", []):
            term = tag.get("term", "")
            if term:
                categories.append(term)

        # 摘要
        abstract = None
        for field in ["summary", "description", "content"]:
            val = entry.get(field, "")
            if isinstance(val, dict):
                val = val.get("value", "")
            if val:
                cleaned = strip_html(val)
                if cleaned:
                    abstract = cleaned
                    break

        articles.append(make_article(
            title=title, link=link, pub_date=item_date,
            authors=authors, doi=doi or None, journal=name,
            source="rss", article_type=infer_type(categories),
            abstract=abstract,
        ))

    return articles, None

# ─── PubMed 抓取 ───

PUBMED_BATCH = 50
PUBMED_TOOL = "PaperPulse"
# NCBI 未认证请求上限为 3 次/秒；GitHub runner 多为共享出口 IP，留出余量
PUBMED_MIN_INTERVAL = float(os.getenv("PUBMED_MIN_INTERVAL", "0.5"))
PUBMED_MAX_RETRIES = 5
_last_pubmed_request_at = 0.0

def _pubmed_throttle() -> None:
    global _last_pubmed_request_at
    wait = PUBMED_MIN_INTERVAL - (time.time() - _last_pubmed_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_pubmed_request_at = time.time()

def pubmed_get(url: str, params: Dict[str, Any]) -> Optional[requests.Response]:
    """带节流与 429/5xx 退避重试的 PubMed 请求。失败返回 None。"""
    for attempt in range(PUBMED_MAX_RETRIES):
        _pubmed_throttle()
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            if attempt == PUBMED_MAX_RETRIES - 1:
                print(f"  [pubmed] request error: {e}")
                return None
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "")
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                wait = 0
            wait = max(wait, 2 ** attempt)
            print(f"  [pubmed] 429 rate limit, retry in {wait:.0f}s")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            if attempt == PUBMED_MAX_RETRIES - 1:
                print(f"  [pubmed] server error: {resp.status_code}")
                return None
            time.sleep(2 ** attempt)
            continue
        return resp
    print("  [pubmed] retries exhausted")
    return None

def normalize_journal_name(name: str) -> str:
    s = name.lower().replace("&", "and")
    for ch in [".", ",", ":", "'", "!", "?"]:
        s = s.replace(ch, "")
    for ch in ["(", ")", "[", "]", "-"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())

def pubmed_esearch(term: str, accept_dates: Set[str], datetype: str = "pdat") -> List[str]:
    sorted_dates = sorted(accept_dates)
    min_date = sorted_dates[0].replace("-", "/") if sorted_dates else ""
    max_date = sorted_dates[-1].replace("-", "/") if sorted_dates else ""
    retmax = max(100, min(500, len(accept_dates) * 50))

    params = {
        "db": "pubmed", "retmode": "json", "retmax": retmax,
        "sort": "pub_date", "datetype": datetype, "tool": PUBMED_TOOL,
        "term": term,
    }
    if min_date and max_date:
        params["mindate"] = min_date
        params["maxdate"] = max_date

    resp = pubmed_get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params
    )
    if resp is None:
        return []
    try:
        data = resp.json()
        result = data.get("esearchresult", {})
        return result.get("idlist", [])
    except Exception as e:
        print(f"  [pubmed] esearch parse error: {e}")
        return []

def pubmed_esummary(pmids: List[str], journal: str, accept_dates: Set[str],
                    index_mode: bool = False, match_name: Optional[str] = None) -> List[Dict]:
    if not pmids:
        return []
    resp = pubmed_get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        {
            "db": "pubmed", "id": ",".join(pmids),
            "retmode": "json", "tool": PUBMED_TOOL,
        },
    )
    if resp is None:
        return []
    try:
        data = resp.json()
        result = data.get("result", {})
    except Exception as e:
        print(f"  [pubmed] esummary parse error: {e}")
        return []

    normalized_expected = normalize_journal_name(match_name or journal)
    articles = []

    for pmid in pmids:
        entry = result.get(pmid, {})
        if not isinstance(entry, dict):
            continue
        title = entry.get("title", "").strip()
        if not title:
            continue
        title = strip_html(title)

        # 期刊名验证
        full_journal = entry.get("fulljournalname", "")
        if full_journal:
            if normalize_journal_name(full_journal) != normalized_expected:
                continue

        # 日期
        # index_mode：按“新收录到 PubMed”抓取（datetype=edat）。这类期刊的 pubdate
        # 常常是未来期号日期，若按 pubdate 过滤会整期丢失；此时优先用 epubdate，
        # 只有当日期落在目标范围内才写 pub_date，否则留空（本次抓取视为当天新增）。
        if index_mode:
            raw_date = entry.get("epubdate") or entry.get("pubdate", "")
            item_date = parse_pubmed_date(raw_date)
            if item_date and item_date not in accept_dates:
                item_date = None
        else:
            pubdate = entry.get("pubdate", "")
            item_date = parse_pubmed_date(pubdate)
            if item_date and item_date not in accept_dates:
                continue

        # 作者
        authors = [a.get("name", "") for a in entry.get("authors", []) if a.get("name")]

        # DOI
        doi = ""
        for aid in entry.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break

        # 文章类型
        pubtypes = entry.get("pubtype", [])
        article_type = best_pub_type(pubtypes) if pubtypes else None

        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

        articles.append(make_article(
            title=title, link=link, pub_date=item_date,
            authors=authors, doi=doi or None, journal=journal,
            source="pubmed", pmid=pmid, article_type=article_type,
        ))

    return articles

def best_pub_type(pubtypes: List[str]) -> Optional[str]:
    priority = [
        "Review", "Editorial", "Letter", "Comment", "Case Reports",
        "Clinical Trial", "Comparative Study", "Meta-Analysis",
        "Systematic Review", "Guideline", "Practice Guideline",
        "Erratum", "Retraction of Publication", "Retracted Publication",
        "Published Erratum", "News", "Newspaper Article",
    ]
    for p in priority:
        for pt in pubtypes:
            if pt.lower() == p.lower():
                return p
    non_generic = [pt for pt in pubtypes if pt != "Journal Article"]
    return non_generic[0] if non_generic else (pubtypes[0] if pubtypes else None)

def pubmed_efetch_abstracts(pmids: List[str]) -> Dict[str, str]:
    """通过 efetch 获取摘要。返回 {pmid: abstract}。"""
    if not pmids:
        return {}
    resp = pubmed_get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        {
            "db": "pubmed", "id": ",".join(pmids),
            "retmode": "xml", "tool": PUBMED_TOOL,
        },
    )
    if resp is None:
        return {}

    # 简单 XML 解析提取摘要
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return {}

    result = {}
    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        pmid = pmid_elem.text if pmid_elem is not None else ""
        if not pmid:
            continue
        abstract_parts = []
        for ab in article.findall(".//Abstract/AbstractText"):
            label = ab.get("Label", "")
            text = "".join(ab.itertext()).strip()
            if text:
                if label:
                    abstract_parts.append(f"[{label}] {text}")
                else:
                    abstract_parts.append(text)
        if abstract_parts:
            result[pmid] = " ".join(abstract_parts)
    return result

def fetch_pubmed(name: str, term: str, accept_dates: Set[str],
                 datetype: str = "pdat",
                 match_name: Optional[str] = None) -> Tuple[List[Dict], Optional[str]]:
    index_mode = datetype == "edat"
    pmids = pubmed_esearch(term, accept_dates, datetype)
    if not pmids:
        return [], None

    all_articles = []
    for i in range(0, len(pmids), PUBMED_BATCH):
        batch = pmids[i:i + PUBMED_BATCH]
        articles = pubmed_esummary(batch, name, accept_dates, index_mode=index_mode,
                                   match_name=match_name)
        all_articles.extend(articles)
        time.sleep(0.3)  # 遵守 NCBI 速率限制

    # 获取摘要
    kept_pmids = [a["pmid"] for a in all_articles if a.get("pmid")]
    for i in range(0, len(kept_pmids), PUBMED_BATCH):
        batch = kept_pmids[i:i + PUBMED_BATCH]
        abstracts = pubmed_efetch_abstracts(batch)
        for a in all_articles:
            if a.get("pmid") in abstracts:
                a["abstract"] = abstracts[a["pmid"]]
        time.sleep(0.3)

    return all_articles, None

# ─── 按日期分组与增量写入 ───

def load_existing_date_file(date_str: str) -> Dict[str, Any]:
    """读取已有的日期 JSON 文件，返回 {journals: {...}} 或空结构。"""
    path = DATA_DIR / f"{date_str}.json"
    if not path.exists():
        return {"journals": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "journals" not in data:
            data["journals"] = {}
        return data
    except (json.JSONDecodeError, IOError):
        return {"journals": {}}


def load_all_existing_ids(data_dir: Path) -> Tuple[Dict[str, str], Set[str]]:
    """读取 data/ 下所有日期文件的已有数据。

    返回 (article_id -> date_str, 跨来源去重键集合)。必须扫描全部日期文件，
    而不是只扫描 accept_dates：RSS 源会连续多天保留同一批条目，如果只看两天，
    这些旧条目每天都会被当成新文章重新写入当天文件，导致列表看起来没有更新。
    """
    id_to_date: Dict[str, str] = {}
    keys: Set[str] = set()
    for path in sorted(data_dir.glob("*.json")):
        if path.name == "index.json" or not _DATE_FILE_RE.fullmatch(path.stem):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            continue
        for journal_name, articles in data.get("journals", {}).items():
            for a in articles:
                aid = article_id(a)
                if aid not in id_to_date:
                    id_to_date[aid] = path.stem
                keys.update(article_keys(a))
    return id_to_date, keys


def assign_date_to_article(a: Dict[str, Any], accept_dates: Set[str],
                           primary_date: str) -> str:
    """根据文章的 pub_date 分配到具体的日期文件。
    如果 pub_date 在 accept_dates 内，归入该日期；否则归入 primary_date。"""
    pd = a.get("pub_date")
    if pd and pd in accept_dates:
        return pd
    return primary_date


def merge_and_dedup(existing_articles: List[Dict],
                    new_articles: List[Dict]) -> List[Dict]:
    """将新文章增量合并到已有文章列表中，基于 article_id 去重。
    已有的文章保留原样，新文章追加到末尾。"""
    seen_ids = set()
    result = []
    # 先放已有的
    for a in existing_articles:
        aid = article_id(a)
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        result.append(a)
    # 再放新的
    for a in new_articles:
        aid = article_id(a)
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        result.append(a)
    return result


# ─── 旧数据清理 ───

# 保留最近 7 天的数据文件（清理一周前的文献）
RETENTION_DAYS = 7

def cleanup_old_data_files(data_dir: Path) -> List[str]:
    """删除 data/ 下超过保留天数的日期 JSON 文件，返回被删除的文件名。"""
    removed = []
    cutoff = datetime.now(BJ_TZ) - timedelta(days=RETENTION_DAYS)
    for f in sorted(data_dir.glob("*.json")):
        if f.name == "index.json":
            continue
        if not _DATE_FILE_RE.fullmatch(f.stem):
            continue
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=BJ_TZ)
        except ValueError:
            continue
        if file_date < cutoff:
            f.unlink()
            removed.append(f.name)
    return removed


# ─── 主流程 ───

def main() -> int:
    print("=== PaperPulse 抓取开始 ===")

    # 加载配置
    if not SOURCES_PATH.exists():
        print(f"错误：找不到 {SOURCES_PATH}")
        return 1
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    accept_dates = get_accept_dates(DAYS_BACK)
    primary_date = get_primary_date()
    print(f"目标日期范围：{sorted(accept_dates)}")
    print(f"主日期（今天）：{primary_date}")

    all_articles: List[Dict] = []
    errors: List[str] = []

    # ─── 抓取 RSS ───
    rss_sources = [s for s in sources.get("rss", []) if s.get("enabled", True)]
    print(f"\n--- RSS 源：{len(rss_sources)} 个 ---")
    for i, src in enumerate(rss_sources, 1):
        name = src["name"]
        url = src["url"]
        print(f"  [{i}/{len(rss_sources)}] {name}", end=" ... ", flush=True)
        articles, err = fetch_rss(name, url, accept_dates)
        if err:
            print(f"失败 ({err})")
            errors.append(f"RSS {name}: {err}")
        else:
            print(f"{len(articles)} 篇")
        if articles:
            all_articles.extend(articles)

    # ─── 抓取 PubMed ───
    pubmed_sources = [s for s in sources.get("pubmed", []) if s.get("enabled", True)]
    print(f"\n--- PubMed 源：{len(pubmed_sources)} 个 ---")
    for i, src in enumerate(pubmed_sources, 1):
        name = src["name"]
        term = src["term"]
        datetype = src.get("datetype", "pdat")
        match_name = src.get("pubmed_name")
        print(f"  [{i}/{len(pubmed_sources)}] {name}", end=" ... ", flush=True)
        articles, err = fetch_pubmed(name, term, accept_dates, datetype, match_name)
        if err:
            print(f"失败 ({err})")
            errors.append(f"PubMed {name}: {err}")
        else:
            print(f"{len(articles)} 篇")
        if articles:
            all_articles.extend(articles)

    print(f"\n=== 抓取完成，共 {len(all_articles)} 篇（去重前） ===")

    # ─── 全局去重 ───
    seen = set()
    deduped = []
    for a in all_articles:
        aid = article_id(a)
        if aid in seen:
            continue
        seen.add(aid)
        deduped.append(a)
    print(f"去重后：{len(deduped)} 篇")

    # ─── 非文章过滤 ───
    filtered = [a for a in deduped if is_real_article(a.get("title", ""))]
    print(f"过滤后：{len(filtered)} 篇")

    # ─── 加载已有数据，构建跨日期去重映射 ───
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing_id_to_date, existing_keys = load_all_existing_ids(DATA_DIR)
    print(f"已有文献 ID 数：{len(existing_id_to_date)}")

    # ─── 按日期分组新文章 ───
    # date_str -> journal_name -> [articles]
    new_by_date: Dict[str, Dict[str, List[Dict]]] = {}
    # 跨日期去重：如果文章已存在于某个日期文件中，则不再加入其他日期
    cross_date_seen = set(existing_id_to_date.keys())

    for a in filtered:
        aid = article_id(a)
        keys = article_keys(a)
        if aid in cross_date_seen or (keys & existing_keys):
            continue  # 已存在于某个日期文件中，跳过
        cross_date_seen.add(aid)
        existing_keys.update(keys)

        date_str = assign_date_to_article(a, accept_dates, primary_date)
        new_by_date.setdefault(date_str, {})
        jname = a.get("journal", "")
        new_by_date[date_str].setdefault(jname, []).append(a)

    # ─── 增量合并到各日期文件 ───
    all_updated_dates: Set[str] = set()

    for date_str, new_journals in new_by_date.items():
        existing_data = load_existing_date_file(date_str)
        existing_journals: Dict[str, List[Dict]] = existing_data.get("journals", {})

        # 合并每个期刊下的文章
        merged_journals: Dict[str, List[Dict]] = {}
        all_journal_names = set(existing_journals.keys()) | set(new_journals.keys())

        for jname in all_journal_names:
            existing_articles = existing_journals.get(jname, [])
            new_articles = new_journals.get(jname, [])
            merged = merge_and_dedup(existing_articles, new_articles)
            if merged:
                merged_journals[jname] = merged

        total_articles = sum(len(arts) for arts in merged_journals.values())
        total_journals = len(merged_journals)

        output = {
            "date": date_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_journals": total_journals,
            "total_articles": total_articles,
            "journals": merged_journals,
        }

        output_path = DATA_DIR / f"{date_str}.json"
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        all_updated_dates.add(date_str)
        new_count = sum(len(arts) for arts in new_journals.values())
        print(f"\n输出：{output_path}（新增 {new_count} 篇，总计 {total_articles} 篇，{total_journals} 个期刊）")

    # ─── 清理旧数据文件 ───
    removed_files = cleanup_old_data_files(DATA_DIR)
    if removed_files:
        print(f"\n清理旧数据文件：{len(removed_files)} 个")
        for name in removed_files[:10]:
            print(f"  - {name}")
        if len(removed_files) > 10:
            print(f"  ... 共 {len(removed_files)} 个")

    # ─── 更新索引 ───
    index_path = DATA_DIR / "index.json"
    existing_dates: Set[str] = set()
    if index_path.exists():
        try:
            existing_dates = set(json.loads(index_path.read_text(encoding="utf-8")).get("dates", []))
        except (json.JSONDecodeError, IOError):
            pass
    # 添加本次更新的日期 + 扫描 data 目录中所有日期文件
    for f in DATA_DIR.glob("*.json"):
        if f.name == "index.json":
            continue
        if _DATE_FILE_RE.fullmatch(f.stem):
            existing_dates.add(f.stem)
    # 保留最近 RETENTION_DAYS 天
    cutoff_date = (datetime.now(BJ_TZ) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    existing_dates = {d for d in existing_dates if d >= cutoff_date}
    index_data = {
        "dates": sorted(existing_dates, reverse=True),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print(f"\n警告：{len(errors)} 个源失败")
        for e in errors[:10]:
            print(f"  - {e}")

    print("\n=== PaperPulse 抓取完成 ===")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"致命错误：{e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
