"""외부 텍스트 안전 검사 — 규칙 기반 프롬프트 인젝션·악성 문구 탐지와 격리 (AI 사용 없음).

수집한 모든 외부 텍스트(제목·본문·레포 설명)는 저장 전에 이 모듈을 거친다.
- 항상: 보이지 않는 문자(zero-width·방향 제어·태그 문자) 제거, 길이 제한
- 의심 패턴이 있으면 원문을 저장하지 않고 격리 문구로 대체한다 (원문은 출처 링크에서 사람이 직접 확인).

검사 규칙은 일부러 설정 파일이 아닌 코드에 둔다 — 데이터·설정 변경만으로 검사를 약화할 수 없게.
같은 모듈을 로컬 scripts/window.py가 AI에 넘기기 직전에 한 번 더 적용한다 (이중 검사).
"""
import hashlib
import re
import unicodedata

# 공식 출처 — 정상 문장에 'system prompt', 'API key' 같은 단어가 흔하므로 고위험 규칙만 적용
TRUSTED_SOURCES = {"changelog", "github_release", "npm", "anthropic_release_notes", "anthropic_apps_notes",
                   "anthropic_news", "anthropic_engineering", "github_org"}

# 제거 대상: 폭 없는 공백·방향 표시·BOM·soft hyphen (이모지용 ZWJ U+200D는 정상 문자라 유지)
HIDDEN_CHARS = re.compile(
    "[\u200b\u200c\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad\U000e0000-\U000e007f]")
# 의심 신호: 방향 뒤집기(Trojan Source) · 유니코드 태그 문자(보이지 않는 ASCII 밀반입)
SUSPICIOUS_HIDDEN = re.compile("[\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]")

# (코드, 심각도, 정규식) — high는 모든 출처, normal은 비공식 출처에만 적용
RULES = [
    ("instruction_override", "high", re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your)\b[^.\n]{0,20}"
        r"\b(instructions?|prompts?|rules|guidelines|messages)\b", re.I)),
    ("instruction_override", "high", re.compile(
        r"(이전|위의|앞의|기존)\s*(의\s*)?(모든\s*)?(지시|명령|지침|프롬프트)[^.\n]{0,10}(무시|잊)", re.I)),
    ("instruction_override", "high", re.compile(r"\bnew\s+instructions?\s*:", re.I)),
    ("role_injection", "high", re.compile(
        r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]|</?(system|assistant|user)_?(prompt|message)?>", re.I)),
    ("role_injection", "normal", re.compile(
        r"(^|\n)\s*(system|assistant|human)\s*:|\byou are (now )?(claude|chatgpt|an? (ai|assistant|llm))\b", re.I)),
    ("role_injection", "normal", re.compile(r"\b(system prompt|developer message)\b", re.I)),
    ("shell_exec", "high", re.compile(
        r"\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z|da)?sh\b|"
        r"\|\s*(iex|invoke-expression)\b|powershell[^\n]{0,30}-e(nc|ncodedcommand)?\s+[a-z0-9+/=]{20,}", re.I)),
    ("shell_exec", "normal", re.compile(
        r"\brm\s+-rf\s+[/~]|\bchmod\s+\+x\b|\bbase64\s+(-d|--decode)\b|\beval\s*\(|"
        r"\b(run|execute)\s+(this|the following)\s+(command|script)\b", re.I)),
    ("exfiltration", "high", re.compile(r"!\[[^\]]*\]\(\s*https?://[^)\s]+\?[^)\s]*=", re.I)),
    ("exfiltration", "normal", re.compile(
        r"\b(send|post|upload|exfiltrate)\b[^.\n]{0,40}\b(to|into)\s+https?://|webhook\.site|requestbin|ngrok\.io", re.I)),
    ("credential_access", "normal", re.compile(
        r"~?/\.ssh/|\bid_(rsa|ed25519)\b|\.credentials\.json|\bANTHROPIC_API_KEY\b|\bGITHUB_TOKEN\b|"
        r"\b(aws_secret_access_key|private[_ ]key)\b", re.I)),
    ("markup", "high", re.compile(
        r"<\s*(script|iframe|object|embed|svg|img)\b|javascript\s*:|data:text/html|\bon(error|load|click|mouseover)\s*=", re.I)),
    ("encoded_blob", "normal", re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")),
]

QUARANTINE_TEXT = "[격리됨: 의심 문구 감지 — 원문은 출처 링크에서 직접 확인]"


def normalize(text):
    """보이지 않는 문자·제어 문자 제거, NFKC 정규화 (전각 문자로 규칙을 피하는 것 방지)."""
    if text is None:
        return None, False
    s = str(text)
    hidden = bool(SUSPICIOUS_HIDDEN.search(s))
    s = HIDDEN_CHARS.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    return s.strip(), hidden


def scan(text, source=None):
    """원문에서 걸린 규칙 코드 목록(중복 제거, 정렬)."""
    if not text:
        return []
    trusted = source in TRUSTED_SOURCES
    s, hidden = normalize(text)
    if trusted:   # 공식 문서가 `<script>`, `curl … | bash` 를 코드 표기로 언급하는 경우는 정상
        s = re.sub(r"`[^`\n]{1,300}`", " ", s)
    flags = {"hidden_unicode"} if hidden else set()
    for code, severity, rx in RULES:
        if trusted and severity != "high":
            continue
        if rx.search(s):
            flags.add(code)
    return sorted(flags)


def clean(text, maxlen, source=None):
    """(안전한 텍스트, flags). flags가 있으면 텍스트는 격리 문구로 대체된다."""
    if text is None:
        return None, []
    flags = scan(text, source)
    if flags:
        return QUARANTINE_TEXT, flags
    s, _ = normalize(text)
    if len(s) > maxlen:
        s = s[:maxlen - 1].rstrip() + "…"
    return s, []


def safe_url(url):
    """http(s) 링크만 허용 (javascript:, data: 등 차단)."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    return u if re.match(r"^https?://[^\s<>\"']+$", u, re.I) else None


def fingerprint(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
