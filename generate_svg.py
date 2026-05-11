#!/usr/bin/env python3
"""
GitHub 个人主页 SVG 卡片生成器。

用法:
    python generate_svg.py --output profile.svg    # 生成中/英双版本
    python generate_svg.py -o card.svg -l zh        # 仅生成中文
    python generate_svg.py -o card.svg -l en        # 仅生成英文

环境变量:
    GITHUB_TOKEN    GitHub 令牌（GraphQL 查询必须，Actions 中自动提供）
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------

USERNAME = "RenAhsAcme"
OUTPUT = "profile.svg"

# 配色方案 — GitHub Dark 为底，辅以微妙的赛博风格强调色
BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT_PRIMARY = "#e6edf3"
TEXT_SECONDARY = "#8b949e"
TEXT_DIM = "#6e7681"
ACCENT_BLUE = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_PURPLE = "#a371f7"
ACCENT_ORANGE = "#d2991d"
ACCENT_CYAN = "#39d2c0"

# 贡献热力图配色（GitHub 风格绿色，针对暗色背景做去饱和处理）
HEAT_COLORS = [
    CARD_BG,     # 0 次
    "#0e4429",   # 1-3 次
    "#006d32",   # 4-7 次
    "#26a641",   # 8-12 次
    "#39d353",   # 13 次以上
]

# 布局常量
WIDTH = 860
PAD = 30
CONTENT_W = WIDTH - 2 * PAD  # 内容区宽度 800
CARD_RX = 8

# 字体栈
# SVG 属性使用双引号，内部字体名使用单引号以避免 XML 解析冲突
FONT_SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', "
             "Helvetica, Arial, sans-serif")
FONT_MONO = ("'SF Mono', 'Fira Code', 'Fira Mono', "
             "'Roboto Mono', 'Courier New', monospace")

# ---------------------------------------------------------------------------
# 国际化 — 需要新增语言时在此处追加
# ---------------------------------------------------------------------------

I18N = {
    "zh": {
        "title": "本科在读",
        "school": "中山大学网络空间安全学院",
        "motto": 'Come up pick up the pace!',
        "sect_research": "研究方向",
        "sect_tech_stack": "技术栈",
        "sect_contrib": "年度贡献",
        "sect_languages": "编程语言",
        "sect_activity": "近期动态",
        "total_label": "合计",
        "updated": "更新于",
        "stat_stars": "已加星标",
        "stat_followers": "关注者",
        "stat_repos": "仓库",
        "stat_contribs": "贡献",
        "research_tags": [
            ("具身智能安全", "#1a2a3a", ACCENT_BLUE),
            ("威胁情报", "#1a2a1a", ACCENT_GREEN),
            ("CTF", "#2a1a1a", ACCENT_ORANGE),
            ("人工智能安全", "#1a1a2a", ACCENT_PURPLE),
        ],
        "tech_stack": [
            ("Python", "#3572A5"),
            ("C / C++", "#f34b7d"),
            ("Rust", "#dea584"),
        ],
        "activity_verbs": {
            "WatchEvent": "星标了",
            "PushEvent": "推送至",
            "PullRequestEvent": "在…发起了 PR",
            "IssuesEvent": "在…提交了 Issue",
            "ForkEvent": "复刻了",
            "CreateEvent": "创建了",
            "DeleteEvent": "删除了",
            "PullRequestReviewEvent": "在…审查了 PR",
            "IssueCommentEvent": "在…发表了评论",
            "ReleaseEvent": "发布了",
            "PublicEvent": "公开了",
        },
        "fallback_contrib": "贡献数据将在首次 Action 运行后加载",
        "fallback_langs": "暂无公开仓库",
        "fallback_activity": "暂无近期公开动态",
    },
    "en": {
        "title": "UGRD",
        "school": "School of Cyber Science and Technology, Sun Yat-sen University",
        "motto": '"Come on pick up the pace!"',
        "sect_research": "Research",
        "sect_tech_stack": "Tech Stack",
        "sect_contrib": "Contributions (Last Year)",
        "sect_languages": "Languages",
        "sect_activity": "Recent Activity",
        "total_label": "Total",
        "updated": "updated",
        "stat_stars": "Stars",
        "stat_followers": "Followers",
        "stat_repos": "Repos",
        "stat_contribs": "Contribs",
        "research_tags": [
            ("Embodied AI Security", "#1a2a3a", ACCENT_BLUE),
            ("Threat Intelligence", "#1a2a1a", ACCENT_GREEN),
            ("Pentesting & CTF", "#2a1a1a", ACCENT_ORANGE),
            ("Artificial Intelligence", "#1a1a2a", ACCENT_PURPLE),
        ],
        "tech_stack": [
            ("Python", "#3572A5"),
            ("C / C++", "#f34b7d"),
            ("Rust", "#dea584"),
        ],
        "activity_verbs": {
            "WatchEvent": "starred",
            "PushEvent": "pushed to",
            "PullRequestEvent": "opened PR in",
            "IssuesEvent": "opened issue in",
            "ForkEvent": "forked",
            "CreateEvent": "created",
            "DeleteEvent": "deleted",
            "PullRequestReviewEvent": "reviewed PR in",
            "IssueCommentEvent": "commented on",
            "ReleaseEvent": "released",
            "PublicEvent": "made public",
        },
        "fallback_contrib": "Contribution data loads after first Action run",
        "fallback_langs": "No public repos yet",
        "fallback_activity": "No recent public activity",
    },
}


# ---------------------------------------------------------------------------
# GitHub API 请求封装
# ---------------------------------------------------------------------------

def _token():
    return os.environ.get("GITHUB_TOKEN", "")


def _headers(use_graphql=False):
    h = {
        "Accept": "application/json" if use_graphql else "application/vnd.github+json",
        "User-Agent": "Profile-SVG-Generator/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _local_avatar_data_uri(path="avatar.png"):
    """读取本地头像文件，返回 base64 data URI。文件不存在则返回空字符串。"""
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    return ""


def api_rest(path):
    """调用 GitHub REST API (GET)，返回解析后的 JSON。失败重试 3 次。"""
    url = f"https://api.github.com/{path}"
    req = Request(url, headers=_headers())
    for attempt in range(3):
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 403 and "rate limit" in exc.read().decode(errors="replace").lower():
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def api_graphql(query):
    """调用 GitHub GraphQL API (POST)，返回解析后的 JSON。失败重试 3 次。"""
    url = "https://api.github.com/graphql"
    data = json.dumps({"query": query}).encode()
    req = Request(url, data=data, headers=_headers(use_graphql=True), method="POST")
    for attempt in range(3):
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 403 and "rate limit" in exc.read().decode(errors="replace").lower():
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


# ---------------------------------------------------------------------------
# 数据获取
# ---------------------------------------------------------------------------

def fetch_all():
    """从 GitHub 获取全部所需数据，整合为一个 dict 返回。

    REST API（无需认证的基础数据）:
        - 用户基本信息（头像、昵称等）
        - 近期公开事件
        - 仓库列表

    GraphQL API（需 GITHUB_TOKEN）:
        - 年度贡献日历
        - 统计数字（Star、Followers、Repos、PR、Issue）
        - 各仓库语言字节数
    """

    # REST: 用户基本信息 + 头像
    user = api_rest(f"users/{USERNAME}")

    # REST: 近期公开事件
    events = api_rest(f"users/{USERNAME}/events/public?per_page=8")
    if not isinstance(events, list):
        events = []

    # REST: 仓库列表（用于语言统计的 fallback）
    repos = api_rest(f"users/{USERNAME}/repos?per_page=100&sort=pushed")
    if not isinstance(repos, list):
        repos = []

    # GraphQL: 贡献日历 + 统计数字 + 语言字节数
    gql_query = """
    query {
      user(login: "%s") {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
        followers { totalCount }
        starredRepositories { totalCount }
        repositories(ownerAffiliations: OWNER, first: 1) { totalCount }
        pullRequests { totalCount }
        issues { totalCount }
        topRepositories(first: 20, orderBy: {field: PUSHED_AT, direction: DESC}) {
          nodes {
            languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node { name color }
              }
            }
          }
        }
      }
    }
    """ % USERNAME

    gql = api_graphql(gql_query)
    gql_user = (gql.get("data") or {}).get("user") or {}

    # 组装返回
    result = {
        "user": user,
        "events": events,
        "repos": repos,
        "gql": gql_user,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return result


# ---------------------------------------------------------------------------
# 数据提取工具函数
# ---------------------------------------------------------------------------

def extract_stats(data):
    gql = data["gql"]
    stars = gql.get("starredRepositories", {}).get("totalCount", 0)
    followers = gql.get("followers", {}).get("totalCount", 0)
    repos = gql.get("repositories", {}).get("totalCount", 0)
    prs = gql.get("pullRequests", {}).get("totalCount", 0)
    contributions = 0
    cal = gql.get("contributionsCollection", {}).get("contributionCalendar", {})
    contributions = cal.get("totalContributions", 0)
    weeks = cal.get("weeks", [])
    return {
        "stars": stars,
        "followers": followers,
        "repos": repos,
        "prs": prs,
        "contributions": contributions,
        "weeks": weeks,
    }


def extract_languages(gql_user):
    """从 GraphQL 数据中汇总各仓库的语言字节数，计算占比并排序。返回前 5 名。"""
    lang_bytes = {}
    total_bytes = 0

    top_repos = gql_user.get("topRepositories", {}).get("nodes") or []

    for repo in top_repos:
        languages = repo.get("languages", {}).get("edges") or []
        for edge in languages:
            name = edge.get("node", {}).get("name", "")
            size = edge.get("size", 0)
            if name and size:
                lang_bytes[name] = lang_bytes.get(name, 0) + size
                total_bytes += size

    # GitHub 官方语言配色 (linguist)，作为识别的补充
    lang_colors = {
        "Python": "#3572A5",
        "C": "#555555",
        "C++": "#f34b7d",
        "C#": "#178600",
        "Rust": "#dea584",
        "JavaScript": "#f1e05a",
        "TypeScript": "#3178c6",
        "Go": "#00ADD8",
        "Java": "#b07219",
        "HTML": "#e34c26",
        "CSS": "#563d7c",
        "SCSS": "#c6538c",
        "Shell": "#89e051",
        "Dockerfile": "#384d54",
        "Makefile": "#427819",
        "CMake": "#DA3434",
        "Vue": "#41b883",
        "Jupyter Notebook": "#DA5B0B",
        "TeX": "#3D6117",
        "Batchfile": "#C1F12E",
        "PowerShell": "#012456",
        "Roff": "#ecdebe",
        "Vim Script": "#199f4b",
        "Lua": "#000080",
        "MATLAB": "#e16737",
        "Assembly": "#6E4C13",
        "Smarty": "#f0c040",
        "PLpgSQL": "#336790",
        "MDX": "#fcb32c",
    }

    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:5]

    result = []
    for lang, bytes_ in sorted_langs:
        pct = (bytes_ / total_bytes * 100) if total_bytes > 0 else 0
        color = lang_colors.get(lang, ACCENT_BLUE)
        result.append({"name": lang, "pct": round(pct, 1), "color": color})

    return result


def extract_events(events, lang="zh"):
    T = I18N.get(lang, I18N["en"])
    icons = {
        "WatchEvent": "⭐",
        "PushEvent": "\U0001f4e6",
        "PullRequestEvent": "\U0001f500",
        "IssuesEvent": "\U0001f41b",
        "ForkEvent": "\U0001f4cd",
        "CreateEvent": "➕",
        "DeleteEvent": "❌",
        "PullRequestReviewEvent": "\U0001f44d",
        "IssueCommentEvent": "\U0001f4ac",
        "ReleaseEvent": "\U0001f680",
        "PublicEvent": "\U0001f513",
    }
    verbs = T["activity_verbs"]

    result = []
    for e in events[:5]:
        etype = e.get("type", "")
        repo_name = e.get("repo", {}).get("name", "")
        created_at = e.get("created_at", "")
        icon = icons.get(etype, "\U0001f4cc")
        verb = verbs.get(etype, etype)

        # Relative time
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rel = _relative_time(dt, lang)
        except (ValueError, TypeError):
            rel = ""

        result.append({
            "icon": icon,
            "verb": verb,
            "repo": repo_name,
            "time": rel,
        })

    return result


def _relative_time(dt, lang="zh"):
    """将 UTC 时间转换为相对时间字符串，中文显示"X 小时前"，英文显示"Xh ago"。"""
    now = datetime.now(timezone.utc)
    diff = now - dt
    mins = int(diff.total_seconds() / 60)
    if lang == "zh":
        if mins < 60:
            return f"{mins} 分钟前"
        hours = mins // 60
        if hours < 24:
            return f"{hours} 小时前"
        days = hours // 24
        if days < 30:
            return f"{days} 天前"
        return f"{days // 30} 个月前"
    else:
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        return f"{days // 30}mo ago"


# ---------------------------------------------------------------------------
# SVG 生成
# ---------------------------------------------------------------------------

def _text(x, y, content, size=13, color=TEXT_PRIMARY, bold=False, anchor="start",
          font=FONT_SANS, opacity=1.0, extra=""):
    """生成 <text> 元素，内容自动做 XML 转义。"""
    fw = 'font-weight="bold" ' if bold else ""
    return (f'<text x="{x}" y="{y}" font-family="{font}" '
            f'font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'{fw}opacity="{opacity}" {extra}>{_esc(content)}</text>')


def _esc(s):
    """XML 特殊字符转义。"""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rect(x, y, w, h, rx=CARD_RX, fill=CARD_BG, stroke=None, opacity=1.0):
    """生成 <rect> 元素，支持圆角和可选描边。"""
    s = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="{rx}" fill="{fill}"{s} opacity="{opacity}"/>')


def _section_label(x, y, text, accent=ACCENT_BLUE):
    """渲染章节标题：左侧强调色条 + 加粗文字。"""
    parts = []
    parts.append(f'<rect x="{x}" y="{y - 12}" width="3" height="16" '
                 f'rx="2" fill="{accent}"/>')
    parts.append(_text(x + 12, y + 1, text, size=14, bold=True))
    return "\n".join(parts)


def _est_text_width(text, font_size=12):
    """估算文本像素宽度。CJK/全角字符按 font_size px，ASCII/半角按 font_size × 0.6 px。"""
    w = 0.0
    for ch in text:
        cp = ord(ch)
        # CJK 统一表意文字、中文标点、全角字符
        if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F
                or 0xFF00 <= cp <= 0xFFEF or 0x2E80 <= cp <= 0x2FDF):
            w += font_size
        else:
            w += font_size * 0.6
    return w


def _badge(x, y, text, bg="#1a2a3a", fg=ACCENT_BLUE):
    """渲染圆角标签。返回 (占用宽度, SVG 片段)，便于调用方排列。"""
    tw = int(_est_text_width(text, font_size=12) + 20)
    parts = []
    parts.append(f'<rect x="{x}" y="{y}" width="{tw}" height="24" '
                 f'rx="12" fill="{bg}"/>')
    parts.append(_text(x + tw / 2, y + 16, text, size=12, color=fg, anchor="middle"))
    return tw + 8, "\n".join(parts)


def _stat_card(x, y, w, h, label, value, color=TEXT_PRIMARY):
    parts = []
    parts.append(_rect(x, y, w, h, rx=6, stroke=BORDER))
    parts.append(_text(x + w / 2, y + 22, str(value), size=20, color=color,
                       bold=True, anchor="middle"))
    parts.append(_text(x + w / 2, y + 42, label, size=11, color=TEXT_SECONDARY,
                       anchor="middle"))
    return "\n".join(parts)


def build_svg(data, lang="zh"):
    T = I18N.get(lang, I18N["en"])
    stats = extract_stats(data)
    languages = extract_languages(data["gql"])
    activities = extract_events(data["events"], lang)

    # 头部信息
    user = data["user"]
    display_name = user.get("name") or user.get("login") or USERNAME
    avatar_url = user.get("avatar_url", "")

    parts = []

    # SVG 外壳 + defs（渐变、滤镜、裁剪路径等）
    parts.append(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{WIDTH}" height="620" viewBox="0 0 {WIDTH} 620">
<defs>
  <clipPath id="avatarClip">
    <circle cx="72" cy="72" r="42"/>
  </clipPath>
  <linearGradient id="headerGrad" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{ACCENT_BLUE}" stop-opacity="0.08"/>
    <stop offset="100%" stop-color="{ACCENT_PURPLE}" stop-opacity="0.04"/>
  </linearGradient>
  <filter id="glow">
    <feGaussianBlur stdDeviation="3" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>

<!-- 背景 -->
<rect width="{WIDTH}" height="620" rx="12" fill="{BG}"/>

<!-- 顶部强调线 -->
<rect x="0" y="0" width="{WIDTH}" height="2" rx="1" fill="{ACCENT_BLUE}" opacity="0.6"/>
''')

    # --- 头部区域 ---
    # 头像：优先使用本地文件（base64 嵌入，无需网络），其次远程 URL，最后首字母占位
    avatar_src = _local_avatar_data_uri() or avatar_url
    if avatar_src:
        parts.append(f'''<!-- 头像 -->
<circle cx="72" cy="72" r="43" fill="{BORDER}"/>
<image x="30" y="30" width="84" height="84" clip-path="url(#avatarClip)"
       xlink:href="{_esc(avatar_src)}" preserveAspectRatio="xMidYMid slice"/>
''')
    else:
        parts.append(f'''<circle cx="72" cy="72" r="42" fill="{BORDER}"/>
<text x="72" y="78" text-anchor="middle" font-family="{FONT_SANS}"
      font-size="28" fill="{TEXT_SECONDARY}">R</text>
''')

    # 用户名
    parts.append(_text(132, 58, display_name, size=22, bold=True))
    # 头衔
    parts.append(_text(132, 84, T["title"], size=14, color=TEXT_SECONDARY))
    # 座右铭
    parts.append(_text(132, 108, T["motto"], size=12, color=TEXT_DIM,
                       extra='font-style="italic"'))
    # 学校
    school_icon = "\U0001f393" if lang == "zh" else "\U0001f393"
    parts.append(_text(132, 130, f"{school_icon}  {T['school']}", size=12,
                       color=TEXT_SECONDARY))

    # --- 统计卡片（右侧） ---
    card_w, card_h = 86, 56
    card_y = 42
    cards_data = [
        (stats["stars"], T["stat_stars"]),
        (stats["followers"], T["stat_followers"]),
        (stats["repos"], T["stat_repos"]),
        (stats["contributions"], T["stat_contribs"]),
    ]
    for i, (val, lbl) in enumerate(cards_data):
        cx = WIDTH - PAD - (4 - i) * (card_w + 10)
        # 大数值缩写
        if val >= 1000:
            disp = f"{val / 1000:.1f}k"
        else:
            disp = str(val)
        parts.append(_stat_card(cx, card_y, card_w, card_h, lbl, disp))

    # --- 分隔线 ---
    parts.append(f'<line x1="{PAD}" y1="150" x2="{WIDTH - PAD}" y2="150" '
                 f'stroke="{BORDER}" stroke-width="1"/>')

    # --- 双栏区域：研究方向（左）| 技术栈（右） ---
    col1_x = PAD
    col2_x = PAD + CONTENT_W // 2 + 20
    sec_y = 175

    # 研究方向
    parts.append(_section_label(col1_x, sec_y, T["sect_research"]))
    badges_y = sec_y + 20
    bx = col1_x
    by = badges_y
    # 右边界：超出此位置则换行，防止侵入右侧"技术栈"区域
    badge_limit = col2_x - 16
    for tag, bg_c, fg_c in T["research_tags"]:
        # 先估算标签宽度，放不下则提前换行（修复溢出 bug）
        est_w = int(_est_text_width(tag) + 20 + 8)
        if bx > col1_x and bx + est_w > badge_limit:
            bx = col1_x
            by += 32
        w_used, svg = _badge(bx, by, tag, bg=bg_c, fg=fg_c)
        parts.append(svg)
        bx += w_used

    # 技术栈（右列）
    parts.append(_section_label(col2_x, sec_y, T["sect_tech_stack"], accent=ACCENT_GREEN))
    tech_y = sec_y + 20
    tx = col2_x
    ty = tech_y
    for tname, tcolor in T["tech_stack"]:
        # 彩色圆点 + 文字
        parts.append(f'<circle cx="{tx + 8}" cy="{ty + 8}" r="5" fill="{tcolor}"/>')
        parts.append(_text(tx + 20, ty + 13, tname, size=13))
        tx += len(tname) * 8 + 40
        if tx > col2_x + 300:
            tx = col2_x
            ty += 28

    # --- 分隔线 ---
    div2_y = max(badges_y + 50, tech_y + 30)
    parts.append(f'<line x1="{PAD}" y1="{div2_y}" x2="{WIDTH - PAD}" y2="{div2_y}" '
                 f'stroke="{BORDER}" stroke-width="1"/>')

    # --- 年度贡献热力图 ---
    heat_y = div2_y + 25
    parts.append(_section_label(PAD, heat_y, T["sect_contrib"],
                                accent=ACCENT_GREEN))
    # 总贡献数
    total_text = f"{T['total_label']}: {stats['contributions']:,}"
    parts.append(_text(WIDTH - PAD, heat_y + 1, total_text,
                       size=12, color=TEXT_SECONDARY, anchor="end"))

    weeks = stats["weeks"]
    heatmap_x = PAD
    heatmap_y = heat_y + 24
    cell_s = 10   # 格子尺寸
    gap = 3       # 间距
    step = cell_s + gap

    # 左侧星期标注
    if lang == "zh":
        day_labels = [("一", 1), ("三", 3), ("五", 5)]
    else:
        day_labels = [("Mon", 1), ("Wed", 3), ("Fri", 5)]
    for lbl, row in day_labels:
        parts.append(_text(heatmap_x - 8, heatmap_y + row * step + cell_s - 2,
                           lbl, size=9, color=TEXT_DIM, anchor="end"))

    # 顶部月份标注
    if lang == "zh":
        months = [f"{i}月" for i in range(1, 13)]
    else:
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_positions = {}

    if weeks:
        for wi, week in enumerate(weeks):
            days = week.get("contributionDays", [])
            if not days:
                continue
            first_day = days[0].get("date", "")
            if first_day:
                try:
                    dt = datetime.strptime(first_day, "%Y-%m-%d")
                    m_abbr = months[dt.month - 1]
                    # 每月只标注首次出现的位置
                    if m_abbr not in month_positions.values():
                        month_positions[wi] = m_abbr
                except (ValueError, IndexError):
                    pass

    for wi, m_abbr in month_positions.items():
        mx = heatmap_x + wi * step + cell_s / 2
        parts.append(_text(mx, heatmap_y - 6, m_abbr, size=9, color=TEXT_DIM,
                           anchor="middle"))

    # 热力图格子
    if weeks:
        for wi, week in enumerate(weeks):
            days = week.get("contributionDays", [])
            for di, day in enumerate(days):
                count = day.get("contributionCount", 0)
                if count == 0:
                    c = HEAT_COLORS[0]
                elif count <= 3:
                    c = HEAT_COLORS[1]
                elif count <= 7:
                    c = HEAT_COLORS[2]
                elif count <= 12:
                    c = HEAT_COLORS[3]
                else:
                    c = HEAT_COLORS[4]

                cx = heatmap_x + wi * step
                cy = heatmap_y + di * step
                parts.append(f'<rect x="{cx}" y="{cy}" width="{cell_s}" '
                             f'height="{cell_s}" rx="2" fill="{c}"/>')
    else:
        # 无数据时生成空占位网格
        for wi in range(52):
            for di in range(7):
                cx = heatmap_x + wi * step
                cy = heatmap_y + di * step
                parts.append(f'<rect x="{cx}" y="{cy}" width="{cell_s}" '
                             f'height="{cell_s}" rx="2" fill="{HEAT_COLORS[0]}"/>')
        parts.append(_text(heatmap_x + 52 * step / 2, heatmap_y + 7 * step / 2 + 4,
                           T["fallback_contrib"],
                           size=11, color=TEXT_DIM, anchor="middle"))

    heat_bottom = heatmap_y + 7 * step + 10

    # --- 编程语言分布 ---
    lang_y = heat_bottom + 20
    parts.append(_section_label(PAD, lang_y, T["sect_languages"], accent=ACCENT_ORANGE))
    lang_y += 24

    if languages:
        bar_area_w = 340
        bar_h = 12
        bar_x = PAD
        for i, lang in enumerate(languages):
            by_ = lang_y + i * 30
            pct = lang["pct"]
            color = lang["color"]
            bar_w = max(bar_area_w * pct / 100, 4)

            parts.append(_text(bar_x, by_ + 10, lang["name"], size=12,
                               color=TEXT_SECONDARY, anchor="end"))
            # 进度条背景
            parts.append(f'<rect x="{bar_x + 8}" y="{by_}" width="{bar_area_w}" '
                         f'height="{bar_h}" rx="6" fill="{CARD_BG}" stroke="{BORDER}" '
                         f'stroke-width="1"/>')
            # 进度条填充
            parts.append(f'<rect x="{bar_x + 8}" y="{by_}" width="{bar_w}" '
                         f'height="{bar_h}" rx="6" fill="{color}"/>')
            # 百分比文字
            parts.append(_text(bar_x + bar_area_w + 16, by_ + 10,
                               f"{pct}%", size=12, color=TEXT_SECONDARY))

        lang_bottom = lang_y + len(languages) * 30
    else:
        lang_bottom = lang_y + 20
        parts.append(_text(PAD + 8, lang_y, T["fallback_langs"], size=12,
                           color=TEXT_DIM))

    # --- 近期动态 ---
    act_y = lang_bottom + 16
    parts.append(_section_label(PAD, act_y, T["sect_activity"], accent=ACCENT_CYAN))
    act_y += 22

    if activities:
        for i, act in enumerate(activities):
            ay = act_y + i * 24
            parts.append(_text(PAD + 2, ay + 1, act["icon"], size=14,
                               color=TEXT_PRIMARY))
            parts.append(_text(PAD + 28, ay + 1,
                               f'{act["verb"]} {act["repo"]}',
                               size=12, color=TEXT_SECONDARY))
            parts.append(_text(WIDTH - PAD, ay + 1, act["time"], size=11,
                               color=TEXT_DIM, anchor="end"))
        act_bottom = act_y + len(activities) * 24 + 8
    else:
        act_bottom = act_y + 20
        parts.append(_text(PAD + 2, act_y, T["fallback_activity"], size=12,
                           color=TEXT_DIM))

    # --- 页脚 ---
    foot_y = max(act_bottom + 10, 590)
    parts.append(f'<line x1="{PAD}" y1="{foot_y - 5}" x2="{WIDTH - PAD}" '
                 f'y2="{foot_y - 5}" stroke="{BORDER}" stroke-width="1"/>')

    # 社交链接
    links = [
        ("\U0001f310", "RenAhsAcme.github.io", "https://RenAhsAcme.github.io"),
        ("\U0001f40d", "github.com/RenAhsAcme", "https://github.com/RenAhsAcme"),
    ]
    lx = PAD
    for icon, text, _ in links:
        parts.append(_text(lx, foot_y + 16, f"{icon}  {text}", size=12,
                           color=TEXT_SECONDARY))
        lx += len(text) * 7 + 60

    parts.append(_text(WIDTH - PAD, foot_y + 16,
                       f"{T['updated']} {data['generated_at']}",
                       size=10, color=TEXT_DIM, anchor="end"))

    # 根据实际内容动态计算 SVG 高度，替换初始占位值
    total_h = foot_y + 36

    parts.append("</svg>")

    svg = "\n".join(parts)
    # 将初始的 height="620" 替换为实际高度
    svg = svg.replace('height="620"', f'height="{total_h}"')
    svg = svg.replace('viewBox="0 0 860 620"', f'viewBox="0 0 860 {total_h}"')
    svg = svg.replace(f'<rect width="860" height="620" rx="12" fill="{BG}"/>',
                      f'<rect width="860" height="{total_h}" rx="12" fill="{BG}"/>')

    return svg


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    global OUTPUT
    # 简易命令行参数解析
    args = sys.argv[1:]
    langs_to_build = []  # 空列表 = 生成全部语言
    i = 0
    while i < len(args):
        if args[i] in ("--output", "-o") and i + 1 < len(args):
            OUTPUT = args[i + 1]
            i += 2
        elif args[i] in ("--lang", "-l") and i + 1 < len(args):
            langs_to_build.append(args[i + 1])
            i += 2
        elif not args[i].startswith("-"):
            OUTPUT = args[i]
            i += 1
        else:
            i += 1

    if not langs_to_build:
        langs_to_build = ["zh", "en"]

    # 如果存在本地头像文件，用作 API 不可用时的后备
    local_avatar = "avatar.png"
    _fallback_avatar = local_avatar if os.path.exists(local_avatar) else ""

    print(f"[*] 正在获取 {USERNAME} 的 GitHub 数据 ...")
    try:
        data = fetch_all()
    except Exception as exc:
        print(f"[!] API 请求失败: {exc}")
        print("[*] 使用后备数据生成 ...")
        data = _fallback_data(_fallback_avatar)

    for lang in langs_to_build:
        suffix = "" if lang == "zh" else f"_{lang}"
        out_name = OUTPUT.replace(".svg", f"{suffix}.svg")
        print(f"[*] 正在生成 {lang} 版本 ...")
        svg = build_svg(data, lang=lang)

        with open(out_name, "w", encoding="utf-8") as f:
            f.write(svg)

        size_kb = os.path.getsize(out_name) / 1024
        print(f"[+] 已写入 {out_name} ({size_kb:.1f} KB)")


def _fallback_data(avatar_url=""):
    """当 GitHub API 不可用时，返回最小后备数据集，确保 SVG 仍能渲染。"""
    return {
        "user": {
            "name": "RenAhsAcme",
            "login": "RenAhsAcme",
            "bio": "Researcher on Embodied AI Security",
            "avatar_url": avatar_url,
        },
        "events": [],
        "repos": [],
        "gql": {
            "contributionsCollection": {
                "contributionCalendar": {
                    "totalContributions": 0,
                    "weeks": [],
                }
            },
            "followers": {"totalCount": 0},
            "starredRepositories": {"totalCount": 0},
            "repositories": {"totalCount": 0},
            "pullRequests": {"totalCount": 0},
            "issues": {"totalCount": 0},
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


if __name__ == "__main__":
    main()
