#!/usr/bin/env python3
"""
GitHub Profile SVG Generator for RenAhsAcme.

Fetches live data from GitHub API (REST + GraphQL) and generates a
dark-minimal profile card SVG. Designed to run via GitHub Actions on
a schedule — zero maintenance after initial setup.

Usage:
    python generate_svg.py [--output profile.svg]

Environment:
    GITHUB_TOKEN    GitHub personal access token (required for GraphQL)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USERNAME = "RenAhsAcme"
OUTPUT = "profile.svg"

# Colors — GitHub-dark inspired palette with subtle cyber accents
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

# Contribution heatmap colours (GitHub-style greens, desaturated for dark bg)
HEAT_COLORS = [
    CARD_BG,     # 0
    "#0e4429",   # 1-3
    "#006d32",   # 4-7
    "#26a641",   # 8-12
    "#39d353",   # 13+
]

# Layout constants
WIDTH = 860
PAD = 30
CONTENT_W = WIDTH - 2 * PAD  # 800
CARD_RX = 8

# Font stacks
# Use single quotes inside — SVG attributes are double-quoted
FONT_SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', "
             "Helvetica, Arial, sans-serif")
FONT_MONO = ("'SF Mono', 'Fira Code', 'Fira Mono', "
             "'Roboto Mono', 'Courier New', monospace")


# ---------------------------------------------------------------------------
# GitHub API helpers
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


def api_rest(path):
    """GET a REST endpoint, return parsed JSON."""
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
    """POST a GraphQL query, return parsed JSON."""
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
# Data fetching
# ---------------------------------------------------------------------------

def fetch_all():
    """Fetch all needed data from GitHub and return a consolidated dict."""

    # -- REST: user profile + avatar
    user = api_rest(f"users/{USERNAME}")

    # -- REST: public events (recent activity)
    events = api_rest(f"users/{USERNAME}/events/public?per_page=8")
    if not isinstance(events, list):
        events = []

    # -- REST: repos for language stats
    repos = api_rest(f"users/{USERNAME}/repos?per_page=100&sort=pushed")
    if not isinstance(repos, list):
        repos = []

    # -- GraphQL: contribution calendar + aggregate stats + language bytes
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

    # -- Build result
    result = {
        "user": user,
        "events": events,
        "repos": repos,
        "gql": gql_user,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return result


# ---------------------------------------------------------------------------
# Data extraction helpers
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
    """Aggregate language bytes across repos from GraphQL data."""
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

    # Standard language colours (GitHub linguist)
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


def extract_events(events):
    icons = {
        "WatchEvent": ("⭐", "starred"),
        "PushEvent": ("\U0001f4e6", "pushed to"),
        "PullRequestEvent": ("\U0001f500", "opened PR in"),
        "IssuesEvent": ("\U0001f41b", "opened issue in"),
        "ForkEvent": ("\U0001f4cd", "forked"),
        "CreateEvent": ("➕", "created"),
        "DeleteEvent": ("❌", "deleted"),
        "PullRequestReviewEvent": ("\U0001f44d", "reviewed PR in"),
        "IssueCommentEvent": ("\U0001f4ac", "commented on"),
        "ReleaseEvent": ("\U0001f680", "released"),
        "PublicEvent": ("\U0001f513", "made public"),
    }

    result = []
    for e in events[:5]:
        etype = e.get("type", "")
        repo_name = e.get("repo", {}).get("name", "")
        created_at = e.get("created_at", "")
        icon, verb = icons.get(etype, ("\U0001f4cc", etype))

        # Relative time
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rel = _relative_time(dt)
        except (ValueError, TypeError):
            rel = ""

        result.append({
            "icon": icon,
            "verb": verb,
            "repo": repo_name,
            "time": rel,
        })

    return result


def _relative_time(dt):
    now = datetime.now(timezone.utc)
    diff = now - dt
    mins = diff.total_seconds() / 60
    if mins < 60:
        return f"{int(mins)}m ago"
    hours = mins / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 30:
        return f"{int(days)}d ago"
    months = days / 30
    return f"{int(months)}mo ago"


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

def _text(x, y, content, size=13, color=TEXT_PRIMARY, bold=False, anchor="start",
          font=FONT_SANS, opacity=1.0, extra=""):
    fw = 'font-weight="bold" ' if bold else ""
    return (f'<text x="{x}" y="{y}" font-family="{font}" '
            f'font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'{fw}opacity="{opacity}" {extra}>{_esc(content)}</text>')


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rect(x, y, w, h, rx=CARD_RX, fill=CARD_BG, stroke=None, opacity=1.0):
    s = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="{rx}" fill="{fill}"{s} opacity="{opacity}"/>')


def _section_label(x, y, text, accent=ACCENT_BLUE):
    """Renders a section header with a coloured left accent bar."""
    parts = []
    parts.append(f'<rect x="{x}" y="{y - 12}" width="3" height="16" '
                 f'rx="2" fill="{accent}"/>')
    parts.append(_text(x + 12, y + 1, text, size=14, bold=True))
    return "\n".join(parts)


def _badge(x, y, text, bg="#1a2a3a", fg=ACCENT_BLUE):
    """Renders a rounded pill badge. Returns the width used so callers can chain."""
    # Approximate text width (7px per char for 12px font)
    tw = len(text) * 7 + 20
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


def build_svg(data):
    stats = extract_stats(data)
    languages = extract_languages(data["gql"])
    activities = extract_events(data["events"])

    # Header info
    user = data["user"]
    display_name = user.get("name") or user.get("login") or USERNAME
    avatar_url = user.get("avatar_url", "")

    parts = []

    # -- SVG wrapper + defs
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

<!-- Background -->
<rect width="{WIDTH}" height="620" rx="12" fill="{BG}"/>

<!-- Subtle top accent line -->
<rect x="0" y="0" width="{WIDTH}" height="2" rx="1" fill="{ACCENT_BLUE}" opacity="0.6"/>
''')

    # -- Header section
    # Avatar placeholder / image
    if avatar_url:
        parts.append(f'''<!-- Avatar -->
<circle cx="72" cy="72" r="43" fill="{BORDER}"/>
<image x="30" y="30" width="84" height="84" clip-path="url(#avatarClip)"
       xlink:href="{_esc(avatar_url)}" preserveAspectRatio="xMidYMid slice"/>
''')
    else:
        parts.append(f'''<circle cx="72" cy="72" r="42" fill="{BORDER}"/>
<text x="72" y="78" text-anchor="middle" font-family="{FONT_SANS}"
      font-size="28" fill="{TEXT_SECONDARY}">R</text>
''')

    # Name
    parts.append(_text(132, 58, display_name, size=22, bold=True))
    # Title
    parts.append(_text(132, 84, "Researcher on Embodied AI Security", size=14,
                       color=TEXT_SECONDARY))
    # Motto
    parts.append(_text(132, 108, '"Come on pick up the pace!"', size=12,
                       color=TEXT_DIM, extra='font-style="italic"'))
    # School tag below
    parts.append(_text(132, 130, "\U0001f393  中山大学 网络空间安全学院", size=12,
                       color=TEXT_SECONDARY))

    # -- Stats cards (right side)
    card_w, card_h = 86, 56
    card_y = 42
    cards_data = [
        (stats["stars"], "Stars"),
        (stats["followers"], "Followers"),
        (stats["repos"], "Repos"),
        (stats["contributions"], "Contribs"),
    ]
    for i, (val, lbl) in enumerate(cards_data):
        cx = WIDTH - PAD - (4 - i) * (card_w + 10)
        # Format large numbers
        if val >= 1000:
            disp = f"{val / 1000:.1f}k"
        else:
            disp = str(val)
        parts.append(_stat_card(cx, card_y, card_w, card_h, lbl, disp))

    # -- Divider
    parts.append(f'<line x1="{PAD}" y1="150" x2="{WIDTH - PAD}" y2="150" '
                 f'stroke="{BORDER}" stroke-width="1"/>')

    # -- Two-column section: Research (left) | Tech Stack (right)
    col1_x = PAD
    col2_x = PAD + CONTENT_W // 2 + 20
    sec_y = 175

    # Research interests
    parts.append(_section_label(col1_x, sec_y, "Research"))
    badges_y = sec_y + 20
    bx = col1_x
    by = badges_y
    research_tags = [
        ("Embodied AI Security", "#1a2a3a", ACCENT_BLUE),
        ("Threat Intelligence", "#1a2a1a", ACCENT_GREEN),
        ("Pentesting & CTF", "#2a1a1a", ACCENT_ORANGE),
        ("Artificial Intelligence", "#1a1a2a", ACCENT_PURPLE),
    ]
    for tag, bg_c, fg_c in research_tags:
        w_used, svg = _badge(bx, by, tag, bg=bg_c, fg=fg_c)
        parts.append(svg)
        bx += w_used
        # Wrap to next line
        if bx > col1_x + 380:
            bx = col1_x
            by += 32

    # Tech Stack (right column)
    parts.append(_section_label(col2_x, sec_y, "Tech Stack", accent=ACCENT_GREEN))
    tech_y = sec_y + 20
    tech_list = [
        ("Python", "#3572A5"),
        ("C / C++", "#f34b7d"),
        ("Rust", "#dea584"),
    ]
    tx = col2_x
    ty = tech_y
    for tname, tcolor in tech_list:
        # Colored dot
        parts.append(f'<circle cx="{tx + 8}" cy="{ty + 8}" r="5" fill="{tcolor}"/>')
        parts.append(_text(tx + 20, ty + 13, tname, size=13))
        tx += len(tname) * 8 + 40
        if tx > col2_x + 300:
            tx = col2_x
            ty += 28

    # -- Divider
    div2_y = max(badges_y + 50, tech_y + 30)
    parts.append(f'<line x1="{PAD}" y1="{div2_y}" x2="{WIDTH - PAD}" y2="{div2_y}" '
                 f'stroke="{BORDER}" stroke-width="1"/>')

    # -- Contribution heatmap
    heat_y = div2_y + 25
    parts.append(_section_label(PAD, heat_y, "Contributions (Last Year)",
                                accent=ACCENT_GREEN))
    # Total label
    parts.append(_text(WIDTH - PAD, heat_y + 1,
                       f"Total: {stats['contributions']:,}",
                       size=12, color=TEXT_SECONDARY, anchor="end"))

    weeks = stats["weeks"]
    heatmap_x = PAD
    heatmap_y = heat_y + 24
    cell_s = 10
    gap = 3
    step = cell_s + gap

    # Day labels (Mon, Wed, Fri)
    day_labels = [("Mon", 1), ("Wed", 3), ("Fri", 5)]
    for lbl, row in day_labels:
        parts.append(_text(heatmap_x - 8, heatmap_y + row * step + cell_s - 2,
                           lbl, size=9, color=TEXT_DIM, anchor="end"))

    # Month labels on top
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_positions = {}  # week_index -> month_abbr

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
                    # Only record first occurrence of each month
                    if m_abbr not in month_positions.values():
                        month_positions[wi] = m_abbr
                except (ValueError, IndexError):
                    pass

    for wi, m_abbr in month_positions.items():
        mx = heatmap_x + wi * step + cell_s / 2
        parts.append(_text(mx, heatmap_y - 6, m_abbr, size=9, color=TEXT_DIM,
                           anchor="middle"))

    # Heatmap cells
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
        # Empty placeholder grid
        for wi in range(52):
            for di in range(7):
                cx = heatmap_x + wi * step
                cy = heatmap_y + di * step
                parts.append(f'<rect x="{cx}" y="{cy}" width="{cell_s}" '
                             f'height="{cell_s}" rx="2" fill="{HEAT_COLORS[0]}"/>')
        parts.append(_text(heatmap_x + 52 * step / 2, heatmap_y + 7 * step / 2 + 4,
                           "(contribution data loads after first Action run)",
                           size=11, color=TEXT_DIM, anchor="middle"))

    heat_bottom = heatmap_y + 7 * step + 10

    # -- Language distribution
    lang_y = heat_bottom + 20
    parts.append(_section_label(PAD, lang_y, "Languages", accent=ACCENT_ORANGE))
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
            # Bar background
            parts.append(f'<rect x="{bar_x + 8}" y="{by_}" width="{bar_area_w}" '
                         f'height="{bar_h}" rx="6" fill="{CARD_BG}" stroke="{BORDER}" '
                         f'stroke-width="1"/>')
            # Bar fill
            parts.append(f'<rect x="{bar_x + 8}" y="{by_}" width="{bar_w}" '
                         f'height="{bar_h}" rx="6" fill="{color}"/>')
            # Percentage
            parts.append(_text(bar_x + bar_area_w + 16, by_ + 10,
                               f"{pct}%", size=12, color=TEXT_SECONDARY))

        lang_bottom = lang_y + len(languages) * 30
    else:
        lang_bottom = lang_y + 20
        parts.append(_text(PAD + 8, lang_y, "(No public repos yet)", size=12,
                           color=TEXT_DIM))

    # -- Recent Activity
    act_y = lang_bottom + 16
    parts.append(_section_label(PAD, act_y, "Recent Activity", accent=ACCENT_CYAN))
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
        parts.append(_text(PAD + 2, act_y, "(No recent public activity)", size=12,
                           color=TEXT_DIM))

    # -- Footer
    foot_y = max(act_bottom + 10, 590)
    parts.append(f'<line x1="{PAD}" y1="{foot_y - 5}" x2="{WIDTH - PAD}" '
                 f'y2="{foot_y - 5}" stroke="{BORDER}" stroke-width="1"/>')

    # Social links
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
                       f"updated {data['generated_at']}",
                       size=10, color=TEXT_DIM, anchor="end"))

    # Dynamic SVG height — use actual bottom
    total_h = foot_y + 36

    # Close SVG (note: we need to patch the height at the top)
    parts.append("</svg>")

    svg = "\n".join(parts)
    # Replace placeholder height with actual calculated height
    svg = svg.replace('height="620"', f'height="{total_h}"')
    svg = svg.replace('viewBox="0 0 860 620"', f'viewBox="0 0 860 {total_h}"')
    svg = svg.replace(f'<rect width="860" height="620" rx="12" fill="{BG}"/>',
                      f'<rect width="860" height="{total_h}" rx="12" fill="{BG}"/>')

    return svg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global OUTPUT
    # Simple arg parsing: --output/-o flag or positional
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--output", "-o") and i + 1 < len(args):
            OUTPUT = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            OUTPUT = args[i]
            i += 1
        else:
            i += 1

    # Try to load avatar from local file as fallback
    local_avatar = "avatar.png"
    _fallback_avatar = local_avatar if os.path.exists(local_avatar) else ""

    print(f"[*] Fetching data for {USERNAME} ...")
    try:
        data = fetch_all()
    except Exception as exc:
        print(f"[!] API fetch failed: {exc}")
        print("[*] Generating with fallback data ...")
        data = _fallback_data(_fallback_avatar)

    print(f"[*] Generating SVG ...")
    svg = build_svg(data)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(svg)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"[+] Written {OUTPUT} ({size_kb:.1f} KB)")


def _fallback_data(avatar_url=""):
    """Return minimal fallback data when the GitHub API is unreachable."""
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
