# Learning Book

Interactive lessons on databases and computer networks. Each lesson is a
self-contained HTML page with diagrams and recall questions.

**Live site:** https://iamadheil.github.io/learning-book/

## Layout

```
<topic>/
  index.html            topic landing page
  assets/style.css      shared stylesheet
  entries/<slug>/
    index.html          the lesson page
    source.md           the lesson source
global-index.html       all topics, with search
```

## How a lesson goes live

1. Add or change a lesson in `<topic>/entries/<slug>/`.
2. Commit and push to `main`.
3. GitHub Actions runs `scripts/build_site.py` and deploys the result.

## What the build publishes

`scripts/build_site.py` copies only the pages that can be served:

- A lesson is published **only if its folder contains `index.html`.**
  A folder with only `source.md` is skipped, and every link to it is removed
  from the topic page and the landing page. Render the page and the next push
  publishes it.
- `.md` files stay in the repository but do not go to the site.
- The build fails if any published page links to a file that is absent.

## The landing page

The build **generates** the landing page. It does not copy `global-index.html`.
The landing page shows one card per notebook (topic) with its lesson count. The
card links to the topic page, which lists the lessons.

The generated page is written to both `index.html` and `global-index.html`, so
the "All topics" link on each topic page reaches it.

Generating the page means the `teach-me` skill cannot overwrite it. To change a
notebook description or its glyph, edit `NOTEBOOKS` in `scripts/build_site.py`.
A topic that is absent from `NOTEBOOKS` gets a card built from its top tags.

Run it locally to see what would be published:

```sh
python3 scripts/build_site.py && open _site/index.html
```
