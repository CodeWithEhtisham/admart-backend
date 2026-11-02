# Blog

- **Write posts:** `/admin/dashboard/` → **Blog** (staff). Title, web address (`/blog/<slug>`), summary
  (also the search description), author, cover image, text, Draft / Published.
- **Text formatting:** `## Heading`, `### Smaller heading`, `- list`, `1. numbered`, `**bold**`, `*italic*`,
  `` `code` ``, `[link](https://...)`, `> quote`, and images via **Insert image** (empty line between blocks).
  It is rendered as React elements (no raw HTML), and only http(s), mailto and `/...` links are allowed.
- **Public pages:** `/blog` and `/blog/<slug>` on the frontend; API `GET /api/blog`, `GET /api/blog/<slug>`
  (published posts only). Images are stored under `MEDIA_ROOT/blog/`.
- **Starter posts:** migration `blog/0002_starter_posts` adds three drafts; edit and publish them.

## Not done yet: sitemap

Search engines find posts faster with a `sitemap.xml`. That needs a backend view plus an nginx route
for `/sitemap.xml` to the backend (deploy config is owner-managed). Until then, submit `/blog` and new
post URLs in Google Search Console.
