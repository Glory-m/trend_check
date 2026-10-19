"""무료 기계 번역 — 키 없이 도는 오픈소스 Argos(기본), 키가 있으면 Azure Translator 무료 등급(F0).

엔진 선택:
  1) GitHub 비밀값 AZURE_TRANSLATOR_KEY 가 있으면 Azure (품질 ↑, 무료 등급은 초과 시 과금 없이 거절).
     키는 환경변수로만 받는다(파일·로그에 남기지 않음).
  2) 없으면 Argos 오픈소스 모델(영→한, MIT). 워크플로가 모델 zip을 받아 TREND_MT_MODEL_ZIP 으로 넘긴다.
     번역은 Actions 서버 안에서만 일어나고 문장을 외부로 보내지 않는다. 키·가입 불필요.
     zip은 rules.yml translate.argos.sha256 과 대조한다(비어 있으면 결과에 해시를 남겨 고정하게 한다).
  3) 둘 다 없으면 이 단계는 건너뛴다.
번역 대상은 최근 며칠의 '높음·보통' 항목 중 아직 한국어 문장이 없는 것.
결과는 data/ko/<날짜>.json에 classified_by: "mt" 로 저장 — /brief의 Claude 번역(classified_by: "ai")이 오면 그것으로 덮어쓴다.
번역문도 외부 출력이므로 validate()를 통과해야만 저장한다.
"""
import hashlib
import html
import json
import os
import re
import tempfile
import zipfile
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


def pick(ctx):
    """번역 대상 고르기 — 최근 N일, 높음 먼저, 개수·글자 수 한도."""
    cfg = ctx.rules.get("translate", {})
    store = ctx.store
    dates = [kst_date(ctx.now - timedelta(days=i)) for i in range(cfg.get("days", 3))]
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
    return have, picked


class Azure:
    model = "azure-translator"

    def __init__(self, client, key, region):
        self.client = client
        self.headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json; charset=UTF-8"}
        if region:
            self.headers["Ocp-Apim-Subscription-Region"] = region

    def translate(self, srcs):
        out = []
        for i in range(0, len(srcs), BATCH):
            chunk = srcs[i:i + BATCH]
            res = self.client.post_json(ENDPOINT, [{"Text": to_html(s)} for s in chunk], self.headers)
            out += [from_html(((r or {}).get("translations") or [{}])[0].get("text")) for r in res]
        return out


MAX_MODEL_BYTES = 1_500_000_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def extract_model(zip_path, dest):
    """Argos 패키지 zip에서 필요한 파일만 꺼낸다 — 경로는 파일 이름만 쓰므로 zip 경로 조작이 통하지 않는다.
    반환: (CTranslate2 모델 폴더, sentencepiece 모델 경로, metadata dict)"""
    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_MODEL_BYTES:
            raise ValueError("모델 zip이 너무 큼")
        bins = [i.filename for i in infos if i.filename.endswith("model/model.bin")]
        if len(bins) != 1:
            raise ValueError("model/model.bin 을 찾지 못함")
        mdir = bins[0][:-len("model.bin")]
        root = mdir[:-len("model/")]
        model_out = os.path.join(dest, "model")
        os.makedirs(model_out, exist_ok=True)
        spm = meta = None
        for i in infos:
            n = i.filename
            if n.startswith(mdir):
                base = n[len(mdir):]
                if not base or os.path.basename(base) != base or "/" in base or base.startswith("."):
                    continue
                target = os.path.join(model_out, base)
            elif n == root + "sentencepiece.model":
                target = spm = os.path.join(dest, "sentencepiece.model")
            elif n == root + "metadata.json":
                meta = json.loads(z.read(i).decode("utf-8"))
                continue
            else:
                continue
            with z.open(i) as src, open(target, "wb") as f:
                for b in iter(lambda: src.read(1 << 20), b""):
                    f.write(b)
        if not spm:
            raise ValueError("sentencepiece.model 을 찾지 못함")
    return model_out, spm, meta if isinstance(meta, dict) else {}


class Argos:
    BATCH = 16

    def __init__(self, zip_path, expected_sha=""):
        self.sha = sha256_file(zip_path)
        if expected_sha and self.sha != expected_sha.lower():
            raise ValueError(f"모델 해시 불일치 (받은 것 {self.sha[:12]}…) — 번역 중단")
        self.pinned = bool(expected_sha)
        import ctranslate2            # 워크플로에서만 설치(requirements-mt.txt) — 로컬·테스트엔 필요 없음
        import sentencepiece
        self._tmp = tempfile.TemporaryDirectory()
        model_dir, spm, meta = extract_model(zip_path, self._tmp.name)
        self.prefix = str(meta.get("target_prefix") or "")
        self.sp = sentencepiece.SentencePieceProcessor(model_file=spm)
        self.tr = ctranslate2.Translator(model_dir, device="cpu")
        ver = re.sub(r"[^0-9A-Za-z._-]", "", str(meta.get("package_version") or ""))[:20]
        self.model = "argos-en_ko" + (f"-{ver}" if ver else "")

    def translate(self, srcs):
        out = []
        for i in range(0, len(srcs), self.BATCH):
            chunk = srcs[i:i + self.BATCH]
            toks = [self.sp.encode(CODE.sub(lambda m: m.group(1), s), out_type=str) for s in chunk]
            kw = {"target_prefix": [[self.prefix]] * len(toks)} if self.prefix else {}
            res = self.tr.translate_batch(toks, beam_size=2, max_decoding_length=200, **kw)
            for s, r in zip(chunk, res):
                hyp = r.hypotheses[0][1:] if self.prefix else r.hypotheses[0]
                ko = " ".join(self.sp.decode(hyp).split())
                # 코드 표기(`...`)는 원문 그대로 남아 있어야 한다 — 기계 번역이 뭉개면 버린다
                out.append(ko if all(c in ko for c in CODE.findall(s)) else None)
        return out

    def close(self):
        self._tmp.cleanup()


def engine_for(ctx):
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    if key:
        return Azure(ctx.client, key, os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()), "azure"
    zp = os.environ.get("TREND_MT_MODEL_ZIP")
    if zp and os.path.isfile(zp):
        try:
            sha = (ctx.rules.get("translate", {}).get("argos") or {}).get("sha256") or ""
            return Argos(zp, sha), "argos"
        except ImportError:
            return None, "skipped (ctranslate2·sentencepiece 미설치 — 기계 번역 꺼짐)"
    return None, "skipped (번역 엔진 없음 — 모델 zip도 Azure 키도 없음)"


def run(ctx, engine=None):
    if engine is None:
        engine, name = engine_for(ctx)
        if engine is None:
            return name
    else:
        name = getattr(engine, "name", "test")
    store = ctx.store
    have, picked = pick(ctx)
    if not picked:
        return f"engine={name} nothing to translate"
    try:
        results = engine.translate([src for _, _, src in picked])
    finally:
        if hasattr(engine, "close"):
            engine.close()
    saved = rejected = 0
    for (d, x, _), ko in zip(picked, results):
        if not ko or validate(ko):
            rejected += 1
            continue
        have[d]["items"][x["id"]] = {"ko": ko, "model": engine.model, "generated_at": store.now_iso,
                                     "classified_by": "mt"}
        saved += 1
    for d, data in have.items():
        if data["items"]:
            data["items"] = dict(sorted(data["items"].items()))
            store.write_json(f"ko/{d}.json", data)
    out = f"engine={name} translated={saved} rejected={rejected} chars={sum(len(s) for _, _, s in picked)}"
    if name == "argos" and not engine.pinned:
        out += f" model_sha256={engine.sha} (rules.yml translate.argos.sha256 에 고정하세요)"
    return out
