"""PreToolUse 훅 — 이 폴더의 Claude가 PC나 레포에 해가 될 명령을 실행하지 못하게 막는다.

Claude Code 권한 deny 규칙은 `sh -c '…'` 같은 우회에 약하다(공식 문서 명시). 그래서 명령 문자열 전체를
정규식으로 검사하는 훅을 한 겹 더 둔다. 걸리면 종료 코드 2 → Claude Code가 실행을 막고 사유를 Claude에게 전달.

차단 대상: 외부에서 받아 실행/네트워크 전송, 패키지·플러그인·MCP 설치, 비밀 정보 읽기, 파괴적 명령,
전역 설정 변경, 강제 push. 꼭 필요하면 사용자가 직접 터미널에서 실행한다.
"""
import json
import re
import sys

RULES = [
    ("네트워크 도구로 외부 접속", r"(?<![\w.-])(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|start-bitstransfer|"
                          r"bitsadmin|certutil\s+.*-urlcache|nc|ncat|netcat|telnet|ftp|sftp|scp|ssh)(?![\w.-])"),
    ("코드 문자열 안에서 네트워크·프로세스 실행", r"(python3?|py|node|deno|bun|ruby|perl)\s+(-[a-z]*c|-e|--eval)\b.*"
                                     r"(urllib|requests|http\.client|socket|fetch\(|subprocess|os\.system|child_process)"),
    ("패키지·플러그인·MCP 설치", r"(?<![\w-])(npm|pnpm|yarn|bun)\s+(i|install|add|ci)\b|(?<![\w-])(npx|bunx|pipx)\s|"
                         r"\bpip3?\s+install\b|\buv\s+(pip|add|tool)\b|\b(cargo|go|gem)\s+install\b|"
                         r"\b(winget|choco|scoop|brew)\s+(install|add)\b|\bapt(-get)?\s+install\b|"
                         r"\bclaude\s+(mcp\s+add|plugin\s+(install|add|marketplace\s+add))"),
    ("인코딩된·동적 코드 실행", r"\b(iex|invoke-expression)\b|-e(nc|ncodedcommand)\s+[a-z0-9+/=]{16,}|"
                       r"\bbase64\s+(-d|--decode)\b.*\|\s*(ba|z)?sh\b|\beval\s+[\"'$]"),
    ("비밀 정보 접근", r"\.ssh[/\\]|id_(rsa|ed25519|ecdsa)\b|\.credentials\.json|\.git-credentials|(^|[\s/\\])\.env(\.|\s|$)|"
                 r"\bgit\s+credential\b|\bcmdkey\b|get-storedcredential|\bsecurity\s+find-(generic|internet)-password|"
                 r"\bprintenv\b|\$env:[a-z_]*(token|key|secret|password)|gh\s+auth\s+token"),
    ("파괴적 명령", r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\.\.|\*|[a-z]:)|\bremove-item\b.*-recurse.*(\s[a-z]:\\|~|\.\.)|"
              r"\bformat(\.com)?\s+[a-z]:|\b(diskpart|mkfs(\.\w+)?)\b|\b(del|erase)\s+/[sq]|\brd\s+/s|\bgit\s+(push\s+.*(--force|-f\b)|reset\s+--hard|"
              r"clean\s+-[a-z]*[fdx])"),
    ("전역 설정·시스템 변경", r"\bgit\s+config\s+(--global|--system)\b|\bsetx\b|\breg\s+(add|delete)\b|set-itemproperty\s+.*hk(lm|cu)|"
                     r"\bschtasks\s+/create\b|\bnetsh\b"),
]
COMPILED = [(name, re.compile(rx, re.I)) for name, rx in RULES]


# git commit 메시지(-m "…")는 사람이 읽는 글이라 검사에서 뺀다. 메시지 밖의 명령(&& curl … 등)은 그대로 검사.
COMMIT_MSG = re.compile(r"""(\bgit\s+commit\b[^\n]*?\s-m\s*)("(?:[^"\\]|\\.)*"|'[^']*')""", re.S)


def check(command):
    """걸린 규칙 이름 목록."""
    command = COMMIT_MSG.sub(r'\1""', command or "")
    return [name for name, rx in COMPILED if rx.search(command)]


def main():
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name", "")
    if tool not in ("Bash", "PowerShell"):
        return 0
    command = (event.get("tool_input") or {}).get("command", "")
    hits = check(command)
    if not hits:
        return 0
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    print(f"보안 훅 차단: {', '.join(hits)}. 이 프로젝트에서는 PC·레포에 해가 될 수 있는 명령을 실행하지 않는다. "
          f"정말 필요하면 사용자에게 이유를 설명하고 사용자가 직접 터미널에서 실행하게 할 것.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
