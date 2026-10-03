# yomez.com static site

Static HTML snapshot of the former WordPress site at yomez.com, served by GitHub Pages from `docs/`.

- `docs/` — the published site. Edit HTML here directly.
- `scripts/build.py` — one-time converter from the Simply Static export (`original/export`, not committed) to `docs/`. Re-running it overwrites `docs/`, so don't run it after hand-editing pages.
- `scripts/redirects.json` — old URLs (from the WordPress Redirection plugin and old post slugs) that `build.py` turns into redirect pages.

Preview locally:

```sh
cd docs && python3 -m http.server 8000   # http://localhost:8000
```
