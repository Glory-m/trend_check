"""시간 규칙: 저장은 UTC(ISO 8601, Z), 표시·파일 분할은 KST.

KST는 서머타임이 없으므로 tz 데이터베이스(Windows에 없음) 대신 고정 오프셋을 쓴다.
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def kst_date(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d")


def fmt_kst(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
