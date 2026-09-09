# Bundled browser dependencies

Runtime assets are served locally; the page does not load library code from a CDN.

- Marked **18.0.12**, MIT. Source: https://registry.npmjs.org/marked/-/marked-18.0.12.tgz
  - `marked.umd.js` SHA-256: `fa0cfbf0181339312eaa3709b577ad698fc21a9baa42d580a3fd1f267b19b4a8`
  - License: `marked-LICENSE.md`.
- DOMPurify **3.4.15**, see the bundled license. Source: https://registry.npmjs.org/dompurify/-/dompurify-3.4.15.tgz
  - `dompurify.min.js` SHA-256: `f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5`
  - License: `dompurify-LICENSE.txt`.

The downloaded npm archives were checked against their registry integrity values. Markdown rendering disables raw HTML, then sanitizes a DOM fragment with an allowlist and verifies link protocols.
