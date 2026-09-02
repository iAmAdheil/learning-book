#!/usr/bin/env python3
"""Build the publishable site into _site/.

Rule: a lesson is published only if its directory contains an index.html.
Lessons that have only source.md are skipped, and any link to them is removed.
Render the missing page and the next push publishes it automatically.
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


def prune_entries_array(markup: str) -> tuple[str, list, int]:
    """Filter the inline `const ENTRIES = [...]` array down to pages in _site."""
    match = re.search(r"const ENTRIES = (\[.*?\]);", markup, re.S)
    if not match:
        return markup, [], 0
    entries = json.loads(match.group(1))
    kept = [e for e in entries if (OUT / e["path"]).is_file()]
    dropped = len(entries) - len(kept)
    if dropped:
        markup = (
            markup[: match.start(1)]
            + json.dumps(kept, ensure_ascii=False)
            + markup[match.end(1) :]
        )
    return markup, kept, dropped


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


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    published, skipped = [], []

    for topic in topic_dirs():
        out_topic = OUT / topic.name
        out_topic.mkdir(parents=True, exist_ok=True)

        assets = topic / "assets"
        if assets.is_dir():
            copy_tree(assets, out_topic / "assets")

        for entry in published_entries(topic):
            copy_tree(entry, out_topic / "entries" / entry.name)
            published.append(f"{topic.name}/{entry.name}")

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

    # global-index.html links a root-level assets/style.css that does not exist in
    # the source tree. Every topic stylesheet is identical, so copy one to the root.
    root_assets = OUT / "assets"
    if not (root_assets / "style.css").is_file():
        for topic in topic_dirs():
            source_css = topic / "assets" / "style.css"
            if source_css.is_file():
                root_assets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_css, root_assets / "style.css")
                print(f"copied {topic.name}/assets/style.css to the site root")
                break

    root_index = ROOT / "global-index.html"
    if root_index.is_file():
        markup = root_index.read_text(encoding="utf-8")
        markup, kept, dropped = prune_entries_array(markup)
        if dropped:
            print(f"pruned {dropped} entry(s) from the global index")
        (OUT / "global-index.html").write_text(markup, encoding="utf-8")
        (OUT / "index.html").write_text(markup, encoding="utf-8")
        (OUT / "global-index.json").write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"published {len(published)} lesson(s)")
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
