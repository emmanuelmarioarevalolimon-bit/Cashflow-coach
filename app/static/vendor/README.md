# Local chat-rendering dependencies

These browser assets are served locally to comply with the application's `script-src 'self'` content-security policy:

- Marked 16.4.1 — Markdown parser
- DOMPurify 3.2.6 — HTML sanitizer
- KaTeX 0.16.22 — LaTeX renderer

Their license texts are in `licenses/`. Only KaTeX's WOFF2 fonts are included because all supported browsers load that format.
