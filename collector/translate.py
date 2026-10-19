"""무료 기계 번역 — Azure AI Translator 무료 등급(F0, 월 200만 자, 초과 시 과금 없이 거절).

키는 GitHub 비밀값 AZURE_TRANSLATOR_KEY / AZURE_TRANSLATOR_REGION 으로만 받는다(파일·로그에 남기지 않음).
키가 없으면 이 단계는 건너뛴다. 번역 대상은 최근 며칠의 '높음·보통' 항목 중 아직 한국어 문장이 없는 것.
결과는 data/ko/<날짜>.json에 classified_by: "mt" 로 저장 — /brief의 Claude 번역(classified_by: "ai")이 오면 그것으로 덮어쓴다.
번역문도 외부 출력이므로 validate()를 통과해야만 저장한다.
"""
import html
import os
import re
from datetime import timedelta

from . import safety
from .timeutil import kst_date

ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&from=en&to=ko&textType=html"
HANGUL = re.compile("[가-힣]")
FORBIDDEN = re.compile(r"https?://|www\.|<[a-z/!]|javascript:|\]\(", re.I)
CODE = re.compile(r"`([^`\n]{1,80})`")
TAG = re.compile(r"<[^>]{0,200}>")
BATCH = 50


def validate(text, max_len=200):
    """한국어 번역문 검증 — 통과하면 None, 아니면 사유."""
    if not isinstance(text, str):
        return "문자열 아님"
    t = " ".join(text.split())
    if not 4 <= len(t) <= max_len:
        return f"길이 {len(t)}자 (4~{max_len}자)"
    if not HANGUL.search(t):
        return "한글 없음"
    if FORBIDDEN.search(t):
        return "링크·HTML·마크다운 포함"
    if safety.must_quarantine(safety.scan(t, "search")):
        return "의심 문구"
    return None


def to_html(text):
    """코드 표기(`...`)는 번역하지 않도록 notranslate로 감싼다. 나머지는 HTML 이스케이프."""
    out, last = [], 0
    for m in CODE.finditer(text):
        out.append(html.escape(text[last:m.start()], quote=False))
        out.append(f'<span class="notranslate">{html.escape(m.group(1), quote=False)}</span>')
        last = m.end()
    out.append(html.escape(text[last:], quote=False))
    return "".join(out)


def from_html(s):
    return " ".join(html.unescape(TAG.sub("", s or "")).split())


def source_text(x):
    """번역할 원문: 저장소 소식은 설명이 핵심, 나머지는 제목."""
    if x.get("type") in ("trending", "candidate_new", "official_repo") and x.get("body") and not x["body"].startswith("[격리됨"):
        return f"{x.get('repo') or ''}: {x['body']}"
    title = x.get("title") or ""
    return re.sub(r"^(HN|GitHub 트렌딩\([^)]*\)|Claude 앱|Anthropic 뉴스|Anthropic 엔지니어링 블로그):\s*", "", title)


def run(ctx):
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    if not key:
        return "skipped (AZURE_TRANSLATOR_KEY 없음 — 기계 번역 꺼짐)"
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
    cfg = ctx.rules.get("translate", {})
    store = ctx.store
    days = cfg.get("days", 3)
    dates = [kst_date(ctx.now - timedelta(days=i)) for i in range(days)]
    have, todo = {}, []
    for d in dates:
        have[d] = store.load_json(f"ko/{d}.json", {"date": d, "items": {}})
        done = set(have[d]["items"])
        for x in store.load_json(f"items/{d}.json", {"items": []})["items"]:
            if x["id"] in done or x.get("quarantined") or x.get("importance") not in ("높음", "보통"):
                continue
            src = source_text(x)
            if 3 <= len(src) <= 600 and not HANGUL.search(src):
                todo.append((d, x, src))
    order = {"높음": 0, "보통": 1}
    todo.sort(key=lambda t: order[t[1]["importance"]])
    todo = todo[:cfg.get("max_items_per_run", 80)]
    budget, picked = cfg.get("max_chars_per_run", 20000), []
    for t in todo:
        if budget - len(t[2]) < 0:
            break
        budget -= len(t[2])
        picked.append(t)
    if not picked:
        return "nothing to translate"
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json; charset=UTF-8"}
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region
    saved = rejected = chars = 0
    for i in range(0, len(picked), BATCH):
        chunk = picked[i:i + BATCH]
        res = ctx.client.post_json(ENDPOINT, [{"Text": to_html(src)} for _, _, src in chunk], headers)
        chars += sum(len(src) for _, _, src in chunk)
        for (d, x, _), r in zip(chunk, res):
            ko = from_html(((r or {}).get("translations") or [{}])[0].get("text"))
            if validate(ko):
                rejected += 1
                continue
            have[d]["items"][x["id"]] = {"ko": ko, "model": "azure-translator", "generated_at": store.now_iso,
                                         "classified_by": "mt"}
            saved += 1
    for d, data in have.items():
        if data["items"]:
            data["items"] = dict(sorted(data["items"].items()))
            store.write_json(f"ko/{d}.json", data)
    return f"translated={saved} rejected={rejected} chars={chars}"
