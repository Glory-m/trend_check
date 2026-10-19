"""커밋 전 안전 검사 — 비밀 키·보이지 않는 문자·금지 파일·대용량 파일이 원격으로 나가는 것을 막는다.

사용: python scripts/guard.py --staged   (pre-commit 훅, Actions 커밋 직전)
      python scripts/guard.py --all      (추적 중인 전체 파일)
문제가 있으면 종료 코드 1로 커밋을 중단시킨다. 걸린 값 자체는 출력하지 않는다(로그 노출 방지).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 5 * 1024 * 1024

SECRET_RULES = [
    ("Anthropic API 키", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("GitHub 토큰", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("AWS 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack 토큰", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("개인 키", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Anthropic 키 사용", re.compile(r"secrets\.ANTHROPIC|ANTHROPIC_API_KEY\s*[:=]\s*\S")),
]
# 보이지 않는 문자 (Trojan Source·태그 문자 밀반입). chr()로 만들어 이 파일 자체에는 그런 문자가 없게 한다.
HIDDEN = re.compile("[" + "".join(map(chr, [0x200B, 0x200C, 0x200E, 0x200F, 0x2060, 0x2061, 0x2062, 0x2063,
                                             0x2064, 0xFEFF])) + chr(0x202A) + "-" + chr(0x202E)
                    + chr(0x2066) + "-" + chr(0x2069) + chr(0xE0000) + "-" + chr(0xE007F) + "]")
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|crt|cer|der|p12|pfx|jks|keystore)|id_rsa.*|id_ed25519.*|"
                             r"\.credentials\.json|settings\.local\.json|.*\.local\..*)$", re.I)
# 개인·회사 식별 키워드는 공개 레포에 적으면 그 자체가 노출이므로, 커밋되지 않는 로컬 파일에서만 읽는다.
PRIVATE_TERMS_FILE = "guard.local.txt"
TEXT_EXT = {".py", ".js", ".mjs", ".html", ".css", ".json", ".yml", ".yaml", ".md", ".txt", ".sh", ".toml", ""}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def files(mode):
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR") if mode == "staged" else git("ls-files")
    return [f for f in out.splitlines() if f]


def private_terms():
    p = ROOT / PRIVATE_TERMS_FILE
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [t.strip().lower() for t in lines if t.strip() and not t.startswith("#")]


def check(paths):
    problems = []
    terms = private_terms()
    for rel in paths:
        p = ROOT / rel
        if FORBIDDEN_NAMES.search(rel):
            problems.append(f"{rel}: 커밋 금지 파일 유형")
            continue
        if not p.is_file():
            continue
        if p.stat().st_size > MAX_BYTES:
            problems.append(f"{rel}: {p.stat().st_size // 1024}KB — 5MB 초과")
        if p.suffix.lower() not in TEXT_EXT:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, rx in SECRET_RULES:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{rel}:{line}: {name} 의심 (값은 출력하지 않음)")
        low = text.lower()
        for i, t in enumerate(terms, 1):
            if t in low:
                line = low.count("\n", 0, low.find(t)) + 1
                problems.append(f"{rel}:{line}: 개인·회사 식별 키워드 #{i} (guard.local.txt) 발견")
        for m in HIDDEN.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{rel}:{line}: 보이지 않는 문자 U+{ord(m.group()):04X}")
            break
    return problems


def check_author():
    """로컬 커밋 이메일이 GitHub noreply인지 — 개인 이메일이 public 레포에 남지 않게."""
    try:
        email = git("config", "user.email").strip()
    except subprocess.CalledProcessError:
        return ["git user.email 미설정"]
    return [] if email.endswith("@users.noreply.github.com") else ["git user.email이 noreply 주소가 아님 — 개인 이메일 노출 위험"]


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true")
    g.add_argument("--all", action="store_true")
    args = ap.parse_args()
    paths = files("staged" if args.staged else "all")
    problems = check(paths) + check_author()
    if problems:
        print("guard: 커밋 중단 —", len(problems), "건", file=sys.stderr)
        for x in problems[:50]:
            print("  ✗", x, file=sys.stderr)
        return 1
    print(f"guard: OK ({len(paths)}개 파일 검사)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
