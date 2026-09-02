#!/usr/bin/env python3
"""Build the publishable site into _site/.

Two rules decide what is published:

1. A lesson is published only if its folder contains an index.html. A folder
   with only source.md is skipped, and every link to it is removed.
2. The landing page is generated here, not copied. It lists the notebooks
   (topics) only. Each notebook card links to its topic page, which lists the
   lessons. Generating it means the teach-me skill cannot overwrite it.

The build fails if any published page links to a file that is absent.
"""

import html
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"

# Directories and files that never go to the site.
SKIP_DIRS = {".git", ".github", "_site", "scripts", "node_modules"}
SKIP_NAMES = {".DS_Store"}
SKIP_SUFFIXES = {".md"}

# One line per notebook, and a glyph for the card. A topic that is absent here
# falls back to a line built from its most common tags.
NOTEBOOKS = {
    "databases": {
        "icon": "▤",
        "blurb": "How a relational database stores, indexes, "
                 "and protects your data.",
    },
    "networks": {
        "icon": "⇄",
        "blurb": "How data moves across a network, one layer at a time.",
    },
}


# --------------------------------------------------------------------------
# source discovery
# --------------------------------------------------------------------------

def topic_dirs():
    for path in sorted(ROOT.iterdir()):
        if path.is_dir() and path.name not in SKIP_DIRS and not path.name.startswith("."):
            if (path / "index.html").is_file():
                yield path


def published_entries(topic: Path):
    entries = topic / "entries"
    if not entries.is_dir():
        return
    for path in sorted(entries.iterdir()):
        if path.is_dir() and (path / "index.html").is_file():
            yield path


def source_entries() -> list[dict]:
    """Read lesson metadata.

    global-index.json is the current index. global-index.html embeds a copy of
    the same data that goes stale, so use it only as a fallback.
    """
    index_json = ROOT / "global-index.json"
    if index_json.is_file():
        return json.loads(index_json.read_text(encoding="utf-8"))
    index_html = ROOT / "global-index.html"
    if index_html.is_file():
        match = re.search(r"const ENTRIES = (\[.*?\]);", index_html.read_text(encoding="utf-8"), re.S)
        if match:
            return json.loads(match.group(1))
    return []


def copy_tree(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.rglob("*")):
        if item.name in SKIP_NAMES or item.suffix in SKIP_SUFFIXES:
            continue
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


# --------------------------------------------------------------------------
# pruning
# --------------------------------------------------------------------------

def prune_entry_cards(markup: str, page_dir: Path) -> tuple[str, int]:
    """Remove <a class="entry-card"> blocks that point at a page not in _site."""
    removed = 0

    def keep(match):
        nonlocal removed
        href = re.search(r'href="([^"]+)"', match.group(0))
        if href and not (page_dir / unquote(href.group(1))).is_file():
            removed += 1
            return ""
        return match.group(0)

    pattern = re.compile(r'\s*<a class="entry-card".*?</a>', re.S)
    return pattern.sub(keep, markup), removed


# --------------------------------------------------------------------------
# landing page
# --------------------------------------------------------------------------

LANDING_CSS = """
    .notebook-shelf {
      max-width: 1100px;
      margin: 2rem auto;
      padding: 0 2rem 4rem;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1.5rem;
    }
    .notebook-card {
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      padding: 2rem 1.75rem 1.5rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      color: inherit;
      text-decoration: none;
      transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
    }
    .notebook-card:hover {
      transform: translateY(-3px);
      border-color: var(--accent);
      box-shadow: 0 2px 4px rgba(0,0,0,.05), 0 12px 28px rgba(0,0,0,.10);
    }
    .notebook-card:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--accent-soft); }
    .landing-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
    .landing-header .subtitle { margin-bottom: 0; }
    .notebook-icon { font-size: 1.75rem; line-height: 1; color: var(--accent); }
    .notebook-title { font-size: 1.5rem; margin: 0; text-transform: capitalize; }
    .notebook-desc { margin: 0; color: var(--text-muted); font-size: 0.95rem; line-height: 1.55; }
    .notebook-meta {
      display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap;
      margin-top: auto; padding-top: 0.9rem; border-top: 1px solid var(--border);
    }
    .notebook-count { font-weight: 600; font-size: 0.9rem; }
    .notebook-open { margin-left: auto; color: var(--accent); font-size: 0.9rem; font-weight: 600; }
    .notebook-card:hover .notebook-open { text-decoration: underline; }
    @media (max-width: 480px) {
      .landing-header { padding: 2rem 1.25rem 1.25rem; }
      .landing-header h1 { font-size: 1.9rem; }
      .notebook-shelf { padding: 0 1.25rem 3rem; grid-template-columns: 1fr; }
    }
"""

LANDING_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Learning Book</title>
  <meta name="description" content="{description}" />
  <script>
    (function() {{
      const saved = localStorage.getItem('teach-theme');
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.dataset.theme = saved || (prefersDark ? 'dark' : 'light');
    }})();
  </script>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23c2410c'/%3E%3Crect x='9' y='7' width='14' height='18' rx='2' fill='%23fff'/%3E%3Crect x='9' y='7' width='4' height='18' fill='%23fde2cf'/%3E%3C/svg%3E" />
  <link rel="stylesheet" href="assets/style.css" />
  <style>{css}  </style>
</head>
<body>
  <header class="landing-header global-header">
    <div class="landing-top">
      <div>
        <h1>Learning Book</h1>
        <p class="subtitle">{subtitle}</p>
      </div>
      <button class="theme-toggle" id="theme-toggle" aria-label="Toggle theme">◐</button>
    </div>
  </header>

  <main class="notebook-shelf">
{cards}
  </main>

  <script>
    const root = document.documentElement;
    const themeBtn = document.getElementById('theme-toggle');
    const updateIcon = () => themeBtn.textContent = root.dataset.theme === 'dark' ? '☀' : '◐';
    updateIcon();
    themeBtn.addEventListener('click', () => {{
      const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      localStorage.setItem('teach-theme', next);
      updateIcon();
    }});
  </script>
</body>
</html>
"""


def top_tags(entries: list[dict], limit: int = 4) -> list[str]:
    counts: dict[str, int] = {}
    for entry in entries:
        for tag in entry.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [tag for tag, _ in ranked[:limit]]


def notebook_card(topic: str, entries: list[dict]) -> str:
    meta = NOTEBOOKS.get(topic, {})
    icon = meta.get("icon", "◆")
    blurb = meta.get("blurb") or ", ".join(top_tags(entries, 5)) + "."
    count = len(entries)
    plural = "lesson" if count == 1 else "lessons"
    return f"""    <a class="notebook-card" href="{html.escape(topic)}/index.html">
      <span class="notebook-icon" aria-hidden="true">{icon}</span>
      <h2 class="notebook-title">{html.escape(topic)}</h2>
      <p class="notebook-desc">{html.escape(blurb)}</p>
      <div class="notebook-meta">
        <span class="notebook-count">{count} {plural}</span>
        <span class="notebook-open">Open →</span>
      </div>
    </a>"""


def build_landing_page(by_topic: dict[str, list[dict]]) -> str:
    total = sum(len(v) for v in by_topic.values())
    books = len(by_topic)
    subtitle = (
        f"{books} {'notebook' if books == 1 else 'notebooks'} · "
        f"{total} {'lesson' if total == 1 else 'lessons'}"
    )
    cards = "\n\n".join(notebook_card(topic, by_topic[topic]) for topic in sorted(by_topic))
    return LANDING_TEMPLATE.format(
        description=f"A learning book of {total} interactive lessons across {books} notebooks.",
        css=LANDING_CSS,
        subtitle=subtitle,
        cards=cards,
    )


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def broken_links() -> list[str]:
    """Report every local href/src in _site that points at a file that is absent."""
    broken = []
    for page in sorted(OUT.rglob("*.html")):
        markup = page.read_text(encoding="utf-8", errors="ignore")
        for raw in re.findall(r'(?:href|src)="([^"]+)"', markup):
            link = html.unescape(raw)
            parsed = urlparse(link)
            if parsed.scheme or parsed.netloc or link.startswith(("#", "data:", "mailto:")):
                continue
            if not parsed.path:
                continue
            target = (page.parent / unquote(parsed.path)).resolve()
            if not (target.is_file() or target.is_dir()):
                broken.append(f"{page.relative_to(OUT)} -> {link}")
    return broken


# --------------------------------------------------------------------------

def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    entries_by_id = {e["id"]: e for e in source_entries()}
    by_topic: dict[str, list[dict]] = {}
    skipped: list[str] = []
    published_count = 0

    for topic in topic_dirs():
        out_topic = OUT / topic.name
        out_topic.mkdir(parents=True, exist_ok=True)

        assets = topic / "assets"
        if assets.is_dir():
            copy_tree(assets, out_topic / "assets")

        for entry in published_entries(topic):
            copy_tree(entry, out_topic / "entries" / entry.name)
            published_count += 1
            record = entries_by_id.get(f"{topic.name}/{entry.name}")
            by_topic.setdefault(topic.name, []).append(
                record or {"id": f"{topic.name}/{entry.name}", "slug": entry.name, "tags": []}
            )

        entries_dir = topic / "entries"
        if entries_dir.is_dir():
            for path in sorted(entries_dir.iterdir()):
                if path.is_dir() and not (path / "index.html").is_file():
                    skipped.append(f"{topic.name}/{path.name}")

        markup = (topic / "index.html").read_text(encoding="utf-8")
        markup, removed = prune_entry_cards(markup, out_topic)
        if removed:
            print(f"pruned {removed} card(s) from {topic.name}/index.html")
        (out_topic / "index.html").write_text(markup, encoding="utf-8")

    # The landing page links a root-level assets/style.css. Every topic
    # stylesheet is identical, so copy one to the site root.
    root_assets = OUT / "assets"
    for topic in topic_dirs():
        source_css = topic / "assets" / "style.css"
        if source_css.is_file():
            root_assets.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_css, root_assets / "style.css")
            break

    landing = build_landing_page(by_topic)
    (OUT / "index.html").write_text(landing, encoding="utf-8")
    # Topic pages link back to ../global-index.html. Serve the same landing page
    # there so the back-link works without editing the generated topic pages.
    (OUT / "global-index.html").write_text(landing, encoding="utf-8")

    published_ids = {e["id"] for group in by_topic.values() for e in group}
    (OUT / "global-index.json").write_text(
        json.dumps(
            [e for e in source_entries() if e["id"] in published_ids],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"published {published_count} lesson(s) in {len(by_topic)} notebook(s)")
    if skipped:
        print(f"skipped {len(skipped)} lesson(s) with no index.html:")
        for name in skipped:
            print(f"  - {name}")

    broken = broken_links()
    if broken:
        print("ERROR: broken local links in the built site:", file=sys.stderr)
        for item in broken:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("no broken local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
