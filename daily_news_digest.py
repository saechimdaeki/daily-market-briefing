import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs

import pytz
import requests
from bs4 import BeautifulSoup


NAVER_FINANCE_HOME_URL = "https://finance.naver.com/"
NAVER_MAIN_NEWS_URL = "https://finance.naver.com/news/mainnews.naver"
GITHUB_PAGES_NEWS_URL = "https://saechimdaeki.github.io/daily-market-briefing/daily_news_digest.json"
KST = pytz.timezone("Asia/Seoul")


def _clean_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _safe_get(url, params=None, timeout=10):
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def _normalize_naver_news_url(url):
    if not url:
        return ""
    absolute = urljoin(NAVER_FINANCE_HOME_URL, url)
    parsed = urlparse(absolute)
    if parsed.netloc == "finance.naver.com" and parsed.path.endswith("/news/news_read.naver"):
        query = parse_qs(parsed.query)
        office_id = (query.get("office_id") or [""])[0]
        article_id = (query.get("article_id") or [""])[0]
        if office_id and article_id:
            return f"https://n.news.naver.com/mnews/article/{office_id}/{article_id}"
    return absolute


def fetch_naver_finance_home_news(limit=8):
    response = _safe_get(NAVER_FINANCE_HOME_URL)
    response.encoding = "euc-kr"
    soup = BeautifulSoup(response.text, "html.parser")

    news_items = []
    seen_urls = set()
    rows = soup.select("div.news_area div.section_strategy ul li")

    for row in rows:
        anchor = row.select_one("a")
        if not anchor:
            continue

        title = _clean_text(anchor.get_text(" ", strip=True))
        href = anchor.get("href", "")
        if not title or not href:
            continue

        url = _normalize_naver_news_url(href)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        news_items.append(
            {
                "title": title,
                "url": url,
                "publisher": "",
                "published_at": "",
                "snippet": "",
                "image_url": "",
                "source_type": "KR_HOME",
            }
        )

        if len(news_items) >= limit:
            break

    return news_items


def fetch_naver_finance_main_news(limit=18):
    response = _safe_get(NAVER_MAIN_NEWS_URL)
    response.encoding = "euc-kr"
    soup = BeautifulSoup(response.text, "html.parser")

    news_items = []
    seen_urls = set()
    rows = soup.select("ul.newsList li") or soup.select("div.mainNewsList li") or soup.select("dd.articleSubject")

    for row in rows:
        anchor = (
            row.select_one("dd.articleSubject a")
            or row.select_one(".articleSubject a")
            or row.select_one("a")
        )
        if not anchor:
            continue

        title = _clean_text(anchor.get_text(" ", strip=True))
        href = anchor.get("href", "")
        if not title or not href:
            continue

        url = _normalize_naver_news_url(href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        container = row if row.name == "li" else row.parent
        publisher_node = container.select_one(".press") or container.select_one("span.press")
        date_node = container.select_one(".wdate") or container.select_one("span.wdate")
        summary_node = (
            container.select_one(".articleSummary")
            or container.select_one("dd.articleSummary")
            or container.select_one(".summary")
        )

        snippet = ""
        if summary_node:
            snippet = _clean_text(summary_node.get_text(" ", strip=True))
            if publisher_node and publisher_node.get_text(strip=True) in snippet:
                snippet = snippet.replace(publisher_node.get_text(strip=True), "").strip()
            if date_node and date_node.get_text(strip=True) in snippet:
                snippet = snippet.replace(date_node.get_text(strip=True), "").strip()

        thumb_node = (
            row.select_one("dt.thumb img")
            or row.select_one(".thumb img")
            or row.select_one("img")
        )

        news_items.append(
            {
                "title": title,
                "url": url,
                "publisher": _clean_text(publisher_node.get_text(strip=True) if publisher_node else "네이버 금융"),
                "published_at": _clean_text(date_node.get_text(strip=True) if date_node else ""),
                "snippet": snippet,
                "image_url": _clean_text(thumb_node.get("src")) if thumb_node and thumb_node.get("src") else "",
                "source_type": "KR",
            }
        )

        if len(news_items) >= limit:
            break

    return news_items


def enrich_article_metadata(article):
    enriched = dict(article)
    try:
        response = _safe_get(_normalize_naver_news_url(article["url"]))
        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")

        og_image = soup.select_one('meta[property="og:image"]')
        og_desc = soup.select_one('meta[property="og:description"]')
        og_title = soup.select_one('meta[property="og:title"]')
        og_author = soup.select_one('meta[property="og:article:author"]')
        desc_meta = soup.select_one('meta[name="description"]')
        publisher_node = soup.select_one(".media_end_head_top_logo")
        published_node = soup.select_one("._ARTICLE_DATE_TIME") or soup.select_one(".media_end_head_info_datestamp_time")

        body_selectors = [
            "#dic_area",
            "#newsct_article",
            "#content",
            ".articleCont",
            ".article_body",
            ".news_end",
        ]
        body_text = ""
        for selector in body_selectors:
            node = soup.select_one(selector)
            if node:
                body_text = _clean_text(node.get_text(" ", strip=True))
                if body_text:
                    break

        publisher = _clean_text(publisher_node.get_text(" ", strip=True) if publisher_node else "")
        if not publisher and og_author and og_author.get("content"):
            publisher = _clean_text(og_author.get("content").split("|")[0])

        enriched["title"] = _clean_text(og_title.get("content")) if og_title and og_title.get("content") else enriched["title"]
        enriched["url"] = response.url
        if og_image and og_image.get("content"):
            enriched["image_url"] = urljoin(response.url, _clean_text(og_image.get("content")))
        else:
            enriched["image_url"] = article.get("image_url", "")
        enriched["publisher"] = publisher or article.get("publisher", "")
        enriched["published_at"] = _clean_text(
            published_node.get("data-date-time") if published_node and published_node.get("data-date-time") else (
                published_node.get_text(" ", strip=True) if published_node else article.get("published_at", "")
            )
        )
        enriched["description"] = _clean_text(
            (og_desc.get("content") if og_desc and og_desc.get("content") else "")
            or (desc_meta.get("content") if desc_meta and desc_meta.get("content") else "")
            or article.get("snippet", "")
        )
        enriched["article_excerpt"] = body_text[:700]
    except Exception as exc:
        print(f"기사 메타데이터 추출 실패: {article.get('url')} / {exc}")
        enriched.setdefault("image_url", "")
        enriched.setdefault("description", article.get("snippet", ""))
        enriched.setdefault("article_excerpt", article.get("snippet", ""))

    return enriched


def _dedupe_articles(articles):
    deduped = []
    seen_urls = set()
    seen_titles = set()
    for article in articles:
        url = article.get("url")
        title_key = _clean_text(article.get("title")).lower()
        if not url or url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        deduped.append(article)
    return deduped


def _parse_json_loose(text):
    raw = _clean_text(text)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def select_major_market_news(client, candidates, market_snapshot, is_morning, max_items=4):
    if not client or not candidates:
        return []

    compact_candidates = []
    for idx, article in enumerate(candidates):
        compact_candidates.append(
            {
                "id": idx,
                "title": article.get("title"),
                "publisher": article.get("publisher"),
                "published_at": article.get("published_at"),
                "snippet": article.get("snippet") or article.get("description"),
                "article_excerpt": article.get("article_excerpt", "")[:400],
                "url": article.get("url"),
            }
        )

    briefing_phase = "오전 브리핑" if is_morning else "오후 브리핑"
    prompt = f"""
너는 한국 주식 투자자를 위한 시장 편집자다.
아래 기사 후보들 중 오늘 {briefing_phase}에 가장 볼 가치가 있는 증권/시장 관련 주요뉴스 {max_items}개를 골라라.

[시장 데이터]
{market_snapshot}

[선정 원칙]
- 금리, 관세, 정책, 실적, 섹터 회전, 수급, 지정학, 대형주/지수 영향도를 우선하라
- 같은 이슈의 중복 기사는 1개만 고르라
- 연성 홍보성 기사, 생활경제성 기사, 시장과 무관한 기업 단신은 제외하라
- title과 url은 절대 새로 만들지 말고 반드시 후보의 id만 선택하라
- why_it_matters와 summary는 제공된 snippet/article_excerpt 안에서만 써라
- 제공된 텍스트에 없는 숫자나 사실을 새로 추가하지 마라

[기사 후보]
{json.dumps(compact_candidates, ensure_ascii=False)}

아래 JSON만 출력해라.
{{
  "selected_news": [
    {{
      "id": 0,
      "why_it_matters": "오늘 시장에서 왜 중요한지 한 줄",
      "summary": "기사 핵심을 1~2문장으로 요약",
      "impact_scope": "Macro | US | Korea | Sector"
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    parsed = _parse_json_loose(response.choices[0].message.content or "")
    selected = parsed.get("selected_news") if isinstance(parsed, dict) else None
    if not isinstance(selected, list):
        return []

    validated = []
    for item in selected[:max_items]:
        if not isinstance(item, dict):
            continue
        news_id = item.get("id")
        if not isinstance(news_id, int) or news_id < 0 or news_id >= len(candidates):
            continue
        source = candidates[news_id]
        validated.append(
            {
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "publisher": source.get("publisher", ""),
                "published_at": source.get("published_at", ""),
                "image_url": source.get("image_url", ""),
                "description": source.get("description", ""),
                "why_it_matters": _clean_text(item.get("why_it_matters", "")),
                "summary": _clean_text(item.get("summary", "")),
                "impact_scope": _clean_text(item.get("impact_scope", "")),
            }
        )
    return validated


def _today_kst_str():
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_existing_daily_news_digest():
    try:
        response = _safe_get(GITHUB_PAGES_NEWS_URL, timeout=8)
        data = response.json()
        if data.get("date") == _today_kst_str():
            return data
    except Exception as exc:
        print(f"기존 뉴스 다이제스트 로드 실패: {exc}")
    return None


def build_daily_news_digest(client, market_snapshot, is_morning, max_items=4):
    if not is_morning:
        existing = load_existing_daily_news_digest()
        if existing:
            return existing
        return {
            "date": _today_kst_str(),
            "generated_at": datetime.now(KST).isoformat(),
            "items": [],
        }

    raw_articles = fetch_naver_finance_home_news(limit=8)
    if not raw_articles:
        raw_articles = fetch_naver_finance_main_news(limit=18)
    enriched = _dedupe_articles([enrich_article_metadata(article) for article in raw_articles])
    selected = select_major_market_news(
        client=client,
        candidates=enriched,
        market_snapshot=market_snapshot,
        is_morning=is_morning,
        max_items=max_items,
    )
    return {
        "date": _today_kst_str(),
        "generated_at": datetime.now(KST).isoformat(),
        "items": selected,
    }


def save_daily_news_digest(output_dir, digest):
    path = os.path.join(output_dir, "daily_news_digest.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(digest, file, ensure_ascii=False, indent=2)
