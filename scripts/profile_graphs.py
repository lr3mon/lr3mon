#!/usr/bin/env python3
"""GitHub 프로필 README용 그래프 생성기 (표준 라이브러리만 사용).

GitHub GraphQL API에서 기여 캘린더와 공개 저장소 언어 정보를 읽어
assets/stats/ 아래에 SVG 네 장을 그립니다.

  overview.svg   3D 기여 캘린더 + 핵심 지표
  weekday.svg    요일별 활동 (7각형 레이더)
  languages.svg  언어 지형 (최대 6각형 레이더)
  monthly.svg    최근 12개월 흐름

사용법:
  GH_TOKEN=... python3 scripts/profile_graphs.py --login lr3mon --out assets/stats
  python3 scripts/profile_graphs.py --data data.json --out /tmp/preview   # 저장된 데이터로 그리기
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import urllib.request
from html import escape

KST = dt.timezone(dt.timedelta(hours=9))

SANS = ("-apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Pretendard', "
        "'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', sans-serif")
MONO = "'SF Mono', SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

C = {
    "bg": "#0F1218",
    "wave": "#131821",
    "line": "#232B36",
    "ring": "#2C3540",
    "text": "#F3F5F8",
    "body": "#E8ECF1",
    "sub": "#A3ACBA",
    "muted": "#6B7787",
    "mint": "#8FE3C0",
    "blue": "#6EA8FE",
    "amber": "#F1B45B",
}
HEAT = ["#1B222C", "#1F4A3E", "#2E7A62", "#4FB592", "#8FE3C0"]
WEEKDAYS_MON_FIRST = ["월", "화", "수", "목", "금", "토", "일"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      nodes {
        name
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


# ---------------------------------------------------------------- data

def fetch(login: str, token: str) -> dict:
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-graphs",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    user = payload["data"]["user"]

    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for d in week["contributionDays"]
    ]

    langs: dict[str, dict] = {}
    repos = 0
    for repo in user["repositories"]["nodes"]:
        if repo["name"].lower() == login.lower():  # 프로필 저장소 자체는 제외
            continue
        repos += 1
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            entry = langs.setdefault(name, {"name": name, "size": 0, "color": edge["node"]["color"] or C["muted"]})
            entry["size"] += edge["size"]

    return {
        "login": login,
        "generated": dt.datetime.now(KST).date().isoformat(),
        "days": days,
        "languages": sorted(langs.values(), key=lambda x: -x["size"]),
        "public_repos": repos,
    }


def summarize(days: list[dict]) -> dict:
    counts = [d["count"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:  # 오늘 아직 기록이 없으면 어제부터 셉니다
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    best = max(days, key=lambda d: (d["count"], d["date"])) if days else {"date": "", "count": 0}
    return {
        "total": sum(counts),
        "longest": longest,
        "current": current,
        "best": best,
        "active": sum(1 for c in counts if c > 0),
        "max": max(counts) if counts else 0,
    }


# ---------------------------------------------------------------- svg helpers

def f(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def pts(points) -> str:
    return " ".join(f"{f(x)},{f(y)}" for x, y in points)


def shade(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c * factor))) for c in (r, g, b)))


def text(x, y, s, size=14, fill=None, weight=None, anchor=None, family="sans", extra=""):
    attrs = [f'x="{f(x)}"', f'y="{f(y)}"', f'font-size="{size}"', f'fill="{fill or C["sub"]}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if family == "mono":
        attrs.append('class="mono"')
    if extra:
        attrs.append(extra)
    return f'<text {" ".join(attrs)}>{escape(str(s))}</text>'


def card(w: int, h: int, title: str, desc: str, body: list[str], defs: str = "") -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="title desc" xml:lang="ko">',
        f'  <title id="title">{escape(title)}</title>',
        f'  <desc id="desc">{escape(desc)}</desc>',
        f"  <style>text {{ font-family: {SANS}; }} .mono {{ font-family: {MONO}; }}</style>",
        f"  <defs>{defs}</defs>" if defs else "",
        f'  <rect width="{w}" height="{h}" rx="20" fill="{C["bg"]}"/>',
        *("  " + line for line in body),
        "</svg>",
        "",
    ])


def header(title: str, subtitle: str, x=56, y=58) -> list[str]:
    return [
        f'<rect x="{x}" y="{y - 13}" width="10" height="10" rx="2.5" fill="{C["mint"]}"/>',
        text(x + 20, y - 2, title, 22, C["text"], 700),
        text(x, y + 26, subtitle, 14, C["muted"]),
    ]


def kdate(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.month}월 {d.day}일"


# ---------------------------------------------------------------- 1. 3D 캘린더

def render_overview(data: dict, st: dict) -> str:
    W, H = 1280, 560
    days = [d for d in data["days"] if d["date"] <= data["generated"]]
    first = dt.date.fromisoformat(days[0]["date"])
    first_sunday = first - dt.timedelta(days=(first.weekday() + 1) % 7)

    ux, uy = 19.2, 3.4   # 주(week) 방향
    vx, vy = -8.5, 7.2   # 요일 방향
    x0, y0 = 150.0, 270.0
    fill = 0.8
    max_h = 92.0
    peak = max(st["max"], 1)

    def P(w, d):
        return x0 + w * ux + d * vx, y0 + w * uy + d * vy

    cells = []
    for item in days:
        day = dt.date.fromisoformat(item["date"])
        w = (day - first_sunday).days // 7
        d = (day.weekday() + 1) % 7  # 일요일 = 0
        cells.append((w, d, item["count"]))
    cells.sort(key=lambda c: (c[0] * uy + c[1] * vy, c[0]))

    inset = (1 - fill) / 2
    body = []
    body += header("지난 1년의 기록", "GitHub 기여 · 칸이 높을수록 많이 남긴 날")

    poly = []
    for w, d, count in cells:
        bx, by = P(w + inset, d + inset)
        a = (bx, by)
        b = (bx + ux * fill, by + uy * fill)
        c = (b[0] + vx * fill, b[1] + vy * fill)
        e = (bx + vx * fill, by + vy * fill)
        if count == 0:
            poly.append(f'<polygon points="{pts([a, b, c, e])}" fill="{HEAT[0]}"/>')
            continue
        ratio = count / peak
        level = 1 + min(3, int(math.sqrt(ratio) * 4 - 1e-9))
        top = HEAT[level]
        h = 5 + (max_h - 5) * ratio ** 0.6
        up = lambda p: (p[0], p[1] - h)
        poly.append(f'<polygon points="{pts([e, c, up(c), up(e)])}" fill="{shade(top, 0.42)}"/>')
        poly.append(f'<polygon points="{pts([b, c, up(c), up(b)])}" fill="{shade(top, 0.62)}"/>')
        poly.append(f'<polygon points="{pts([up(a), up(b), up(c), up(e)])}" fill="{top}"/>')
    body.append('<g stroke="#0F1218" stroke-width=".4" stroke-linejoin="round">')
    body += ["  " + p for p in poly]
    body.append("</g>")

    # 요일 라벨
    for d, label in ((1, "월"), (3, "수"), (5, "금")):
        x, y = P(-0.35, d + 0.5)
        body.append(text(x, y + 4, label, 12, C["muted"], anchor="end"))

    # 월 라벨 (앞쪽 가장자리 아래)
    last_month = None
    weeks = max(c[0] for c in cells) + 1
    for w in range(weeks):
        sunday = first_sunday + dt.timedelta(days=7 * w)
        month_day = next((sunday + dt.timedelta(days=i) for i in range(7)
                          if (sunday + dt.timedelta(days=i)).day == 1), None)
        if month_day and month_day.month != last_month and w < weeks - 1:
            x, y = P(w + 0.3, 8.1)
            body.append(text(x, y + 4, f"{month_day.month}월", 12, C["muted"]))
            last_month = month_day.month

    # 지표
    best = st["best"]
    blocks = [
        (56, 122, "지난 1년 기여", f"{st['total']:,}", "건"),
        (348, 122, "가장 많이 남긴 날", f"{best['count']}" if best["count"] else "–",
         f"건 · {kdate(best['date'])}" if best["count"] else ""),
        (640, 122, "최장 연속", f"{st['longest']}", "일"),
        (932, 122, "기록을 남긴 날", f"{st['active']}", "일"),
    ]
    for i, (x, y, label, value, unit) in enumerate(blocks):
        if i:
            body.append(f'<path d="M{x - 28} {y - 10}V{y + 48}" stroke="{C["line"]}"/>')
        body.append(text(x, y, label, 14, C["muted"]))
        body.append(f'<text x="{x}" y="{y + 44}" fill="{C["text"]}" font-size="40" font-weight="700" '
                    f'letter-spacing="-1">{escape(value)}<tspan font-size="16" font-weight="500" '
                    f'fill="{C["sub"]}" dx="6">{escape(unit)}</tspan></text>')

    # 범례
    lx, ly = 56, 516
    body.append(text(lx, ly + 11, "적음", 12, C["muted"]))
    for i, col in enumerate(HEAT):
        body.append(f'<rect x="{lx + 34 + i * 18}" y="{ly}" width="13" height="13" rx="3" fill="{col}"/>')
    body.append(text(lx + 34 + 5 * 18 + 6, ly + 11, "많음", 12, C["muted"]))
    body.append(text(W - 56, 56, f"{data['generated']} 기준 · 매일 자동 갱신", 12, C["muted"], anchor="end"))

    desc = (f"지난 1년 GitHub 기여 {st['total']}건을 3D 캘린더로 표현. 최장 연속 {st['longest']}일, "
            f"기록을 남긴 날 {st['active']}일.")
    return card(W, H, "지난 1년의 기록", desc, body)


# ---------------------------------------------------------------- 레이더 공통

def radar(title, subtitle, labels, values, sublabels, dot_colors, note, desc) -> str:
    W, H = 640, 540
    cx, cy, R = 320.0, 292.0, 138.0
    n = len(labels)
    ang = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]

    def at(i, r):
        return cx + r * math.cos(ang[i]), cy + r * math.sin(ang[i])

    body = header(title, subtitle, 40, 58)
    for k, frac in enumerate((0.25, 0.5, 0.75, 1.0)):
        stroke = C["ring"] if frac == 1.0 else C["line"]
        body.append(f'<polygon points="{pts([at(i, R * frac) for i in range(n)])}" fill="none" stroke="{stroke}"/>')
    for i in range(n):
        x, y = at(i, R)
        body.append(f'<path d="M{f(cx)} {f(cy)}L{f(x)} {f(y)}" stroke="{C["line"]}"/>')

    data_pts = [at(i, R * max(v, 0.035)) for i, v in enumerate(values)]
    body.append(f'<polygon points="{pts(data_pts)}" fill="{C["mint"]}" fill-opacity=".2" '
                f'stroke="{C["mint"]}" stroke-width="2.2" stroke-linejoin="round"/>')
    for (x, y), col in zip(data_pts, dot_colors):
        body.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="5" fill="{col}" stroke="{C["bg"]}" stroke-width="2"/>')

    for i, (label, sub) in enumerate(zip(labels, sublabels)):
        x, y = at(i, R + 26)
        cs, sn = math.cos(ang[i]), math.sin(ang[i])
        anchor = "start" if cs > 0.25 else "end" if cs < -0.25 else "middle"
        if sn < -0.6:
            ly = y - 14
        elif sn > 0.6:
            ly = y + 10
        else:
            ly = y - 2
        body.append(text(x, ly, label, 16, C["body"], 600, anchor))
        body.append(text(x, ly + 18, sub, 13, C["muted"], anchor=anchor))

    body.append(text(40, H - 24, note, 13, C["muted"]))
    return card(W, H, title, desc, body)


# ---------------------------------------------------------------- 2. 요일별

def render_weekday(data: dict, st: dict) -> str:
    sums = [0] * 7  # 월=0 … 일=6
    for d in data["days"]:
        sums[dt.date.fromisoformat(d["date"]).weekday()] += d["count"]
    top = max(sums) or 1
    total = sum(sums) or 1
    best = max(range(7), key=lambda i: sums[i])
    note = (f"가장 활발한 요일 · {WEEKDAYS_MON_FIRST[best]}요일 ({sums[best] * 100 / total:.0f}%)"
            if sum(sums) else "아직 기록이 없습니다")
    return radar(
        "요일별 리듬", "지난 1년 기여를 요일별로 모았습니다",
        WEEKDAYS_MON_FIRST, [s / top for s in sums], [f"{s:,}건" for s in sums],
        [C["mint"]] * 7, note,
        "요일별 기여 수 7각형 레이더. " + ", ".join(f"{d} {s}" for d, s in zip(WEEKDAYS_MON_FIRST, sums)),
    )


# ---------------------------------------------------------------- 3. 언어

def render_languages(data: dict, st: dict) -> str:
    langs = data["languages"][:6]
    total = sum(l["size"] for l in data["languages"]) or 1
    if len(langs) < 3:  # 3개 미만이면 다각형이 안 되므로 빈 축으로 채웁니다
        langs = langs + [{"name": "–", "size": 0, "color": C["muted"]}] * (3 - len(langs))
    top = max(l["size"] for l in langs) or 1
    return radar(
        "언어 지형", "공개 저장소의 코드 용량 기준",
        [l["name"] for l in langs],
        [math.sqrt(l["size"] / top) for l in langs],
        [f"{l['size'] * 100 / total:.1f}%" for l in langs],
        [l["color"] for l in langs],
        f"공개 저장소 {data.get('public_repos', 0)}곳 · 포크 제외 · 축 길이는 비중의 제곱근",
        "공개 저장소 언어 비중 레이더. " + ", ".join(
            f"{l['name']} {l['size'] * 100 / total:.1f}%" for l in langs if l["size"]),
    )


# ---------------------------------------------------------------- 4. 월별

def render_monthly(data: dict, st: dict) -> str:
    W, H = 1280, 360
    today = dt.date.fromisoformat(data["generated"])
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    sums = {k: 0 for k in months}
    for d in data["days"]:
        day = dt.date.fromisoformat(d["date"])
        if (day.year, day.month) in sums:
            sums[(day.year, day.month)] += d["count"]
    vals = [sums[k] for k in months]

    peak = max(vals) or 1
    step = 10 ** max(0, len(str(peak)) - 1)
    nice = math.ceil(peak / step) * step
    if nice / step <= 2 and step >= 10:
        step //= 2
        nice = math.ceil(peak / step) * step
    nice = max(nice, 4)

    left, right, top, base = 96.0, 1216.0, 122.0, 284.0
    xs = [left + (right - left) * i / 11 for i in range(12)]
    ys = [base - (base - top) * v / nice for v in vals]

    body = header("월별 흐름", "최근 12개월, 달마다 남긴 기여")
    avg = sum(vals) / 12
    body.append(text(W - 56, 46, f"{sum(vals):,}건", 28, C["text"], 700, "end"))
    body.append(text(W - 56, 72, f"12개월 합계 · 월평균 {avg:.0f}건", 13, C["muted"], anchor="end"))

    for frac in (0, 0.5, 1):
        gy = base - (base - top) * frac
        dash = ' stroke-dasharray="3 5"' if frac else ""
        body.append(f'<path d="M{f(left)} {f(gy)}H{f(right)}" stroke="{C["line"]}"{dash}/>')
        body.append(text(left - 16, gy + 4, f"{round(nice * frac):,}", 12, C["muted"], anchor="end"))

    # 부드러운 곡선 (Catmull-Rom → Bezier, 기준선 밖으로 넘치지 않게)
    def clamp(v):
        return max(top - 6, min(base, v))

    d = f"M{f(xs[0])} {f(ys[0])}"
    for i in range(11):
        p0 = (xs[i - 1], ys[i - 1]) if i else (xs[i], ys[i])
        p1, p2 = (xs[i], ys[i]), (xs[i + 1], ys[i + 1])
        p3 = (xs[i + 2], ys[i + 2]) if i + 2 < 12 else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, clamp(p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, clamp(p2[1] - (p3[1] - p1[1]) / 6))
        d += f" C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p2[0])} {f(p2[1])}"
    area = d + f" L{f(xs[-1])} {f(base)} L{f(xs[0])} {f(base)} Z"
    body.append(f'<path d="{area}" fill="url(#mfill)"/>')
    body.append(f'<path d="{d}" fill="none" stroke="{C["mint"]}" stroke-width="2.5" stroke-linecap="round"/>')

    best = max(range(12), key=lambda i: vals[i])
    for i, ((yr, mo), v, x, yv) in enumerate(zip(months, vals, xs, ys)):
        is_best = i == best and v > 0
        body.append(f'<circle cx="{f(x)}" cy="{f(yv)}" r="{6 if is_best else 4}" '
                    f'fill="{C["amber"] if is_best else C["mint"]}" stroke="{C["bg"]}" stroke-width="2"/>')
        body.append(text(x, yv - 14, f"{v:,}", 13 if is_best else 12,
                         C["text"] if is_best else C["sub"], 700 if is_best else None, "middle"))
        body.append(text(x, base + 28, f"{mo}월", 13, C["sub"], anchor="middle"))
        if i == 0 or mo == 1:
            body.append(text(x, base + 46, str(yr), 11, C["muted"], anchor="middle"))

    defs = (f'<linearGradient id="mfill" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{C["mint"]}" stop-opacity=".32"/>'
            f'<stop offset="1" stop-color="{C["mint"]}" stop-opacity="0"/></linearGradient>')
    desc = "최근 12개월 월별 기여 수: " + ", ".join(f"{mo}월 {v}" for (_, mo), v in zip(months, vals))
    return card(W, H, "월별 흐름", desc, body, defs)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", default=os.environ.get("PROFILE_LOGIN", "lr3mon"))
    ap.add_argument("--out", default="assets/stats")
    ap.add_argument("--data", help="API 대신 이 JSON 파일로 그립니다")
    ap.add_argument("--dump", help="가져온 데이터를 JSON으로 저장합니다")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("GH_TOKEN 또는 GITHUB_TOKEN 환경 변수가 필요합니다.", file=sys.stderr)
            return 1
        data = fetch(args.login, token)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)

    st = summarize([d for d in data["days"] if d["date"] <= data["generated"]])
    os.makedirs(args.out, exist_ok=True)
    outputs = {
        "overview.svg": render_overview(data, st),
        "weekday.svg": render_weekday(data, st),
        "languages.svg": render_languages(data, st),
        "monthly.svg": render_monthly(data, st),
    }
    for name, svg in outputs.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            fh.write(svg)
    print(f"{len(outputs)}개 그래프 생성 → {args.out} (기여 {st['total']}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
