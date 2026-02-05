#!/usr/bin/env python3
import os
import json
import re
import html
import urllib.request
from pathlib import Path
from collections import defaultdict

GRAPHQL_URL = "https://api.github.com/graphql"

# DON'T FORGET THIS IS HERE !!!
EXCLUDE_REPOS = {
    # "some-repo-name",
}
EXCLUDE_LANGS = {
    "Jupyter Notebook"
}
MAX_ROWS = 10

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(
      first: 100,
      after: $cursor,
      ownerAffiliations: OWNER,
      isFork: false,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isArchived
        languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name }
          }
        }
      }
    }
  }
}
"""

def graphql(token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tomadavis-lang-stats",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]

def pct(size: int, total: int) -> float:
    return (size / total) if total else 0.0

def pct_str(p: float) -> str:
    return f"{p*100:.1f}%"

def bar(p: float, width: int = 18) -> str:
    filled = int(round(p * width))
    return "█" * filled + " " * (width - filled)

def make_table(items, total_bytes: int) -> str:
    lines = [
        "### 📊 Language usage",
        "",
        "| Language | Share | Usage |",
        "|---|---:|:---|",
    ]
    for name, size in items[:MAX_ROWS]:
        p = pct(size, total_bytes)
        lines.append(f"| {name} | {pct_str(p)} | `{bar(p)}` |")
    return "\n".join(lines)

def esc(s: str) -> str:
    return html.escape(s, quote=True)

def make_svg(items, total_bytes: int, out_path: Path, dark: bool) -> None:
    # simple, clean horizontal bar list
    width = 740
    left = 18
    header_h = 46
    row_h = 26
    rows = min(MAX_ROWS, len(items))
    height = header_h + rows * row_h + 18

    # colours (kept neutral so it looks good with your current README)
    bg   = "#0d1117" if dark else "#ffffff"
    fg   = "#e6edf3" if dark else "#24292f"
    mute = "#8b949e" if dark else "#57606a"
    bar_bg = "#30363d" if dark else "#eaeef2"
    bar_fg = "#58a6ff" if dark else "#0969da"

    title = "Languages used across repositories"

    name_x = left
    pct_x  = 210
    bar_x  = 240
    bar_w  = width - bar_x - 18

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" rx="14" fill="{bg}"/>')
    parts.append(
        f'<text x="{left}" y="30" fill="{fg}" font-size="18" '
        f'font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial">{esc(title)}</text>'
    )
    parts.append(
        f'<text x="{left}" y="48" fill="{mute}" font-size="12" '
        f'font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial">GitHub Linguist byte counts</text>'
    )

    y0 = header_h
    for i, (name, size) in enumerate(items[:rows]):
        p = pct(size, total_bytes)
        y = y0 + i * row_h

        parts.append(
            f'<text x="{name_x}" y="{y+17}" fill="{fg}" font-size="14" '
            f'font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial">{esc(name)}</text>'
        )
        parts.append(
            f'<text x="{pct_x}" y="{y+17}" fill="{mute}" font-size="13" text-anchor="end" '
            f'font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial">{esc(pct_str(p))}</text>'
        )

        parts.append(f'<rect x="{bar_x}" y="{y+8}" width="{bar_w}" height="10" rx="5" fill="{bar_bg}"/>')
        parts.append(f'<rect x="{bar_x}" y="{y+8}" width="{max(0.0, p*bar_w):.2f}" height="10" rx="5" fill="{bar_fg}"/>')

    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")

def update_readme(readme: Path, new_block: str) -> None:
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    pattern = r"<!-- LANGUAGES:START -->.*?<!-- LANGUAGES:END -->"
    replacement = f"<!-- LANGUAGES:START -->\n{new_block}\n<!-- LANGUAGES:END -->"

    if re.search(pattern, text, flags=re.DOTALL):
        text = re.sub(pattern, replacement, text, flags=re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + replacement + "\n"

    readme.write_text(text, encoding="utf-8")

def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Missing GITHUB_TOKEN.")

    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("GITHUB_ACTOR")
    if not owner:
        raise SystemExit("Could not determine username.")

    totals = defaultdict(int)
    cursor = None

    while True:
        data = graphql(token, QUERY, {"login": owner, "cursor": cursor})
        repos = data["user"]["repositories"]

        for repo in repos["nodes"]:
            name = repo.get("name")
            if not name or repo.get("isArchived"):
                continue
            if name in EXCLUDE_REPOS:
                continue

            for edge in (repo.get("languages", {}).get("edges", []) or []):
                lang = edge["node"]["name"]
                if lang in EXCLUDE_LANGS:
                    continue
                totals[lang] += int(edge["size"])

        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    total_bytes = sum(size for _, size in items)

    Path("assets").mkdir(parents=True, exist_ok=True)
    make_svg(items, total_bytes, Path("assets/languages-light.svg"), dark=False)
    make_svg(items, total_bytes, Path("assets/languages-dark.svg"), dark=True)

    table = make_table(items, total_bytes)
    update_readme(Path("README.md"), table)

if __name__ == "__main__":
    main()
