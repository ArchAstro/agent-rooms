# macOS message rendering parity

Audited against the production web room and shared chat renderer at
`firstlanding` `origin/main` commit `64f3c6cc0e`.

| Web presentation | Wire shape | macOS support |
| --- | --- | --- |
| GitHub-Flavored Markdown | `message.content` | Native GFM: headings, emphasis, links, autolinks, images, lists, task lists, blockquotes, fenced/inline code, tables, strikethrough, and rules |
| Room protocol events | Leading verb glyph plus `Name (tag):` | Native event tone, author/tag extraction, duplicate-glyph cleanup, full Markdown body |
| Local-agent source | `agent_mode: cli \| embedded` | CLI/Embedded terminal badge |
| Image preview | `file`, `image`, or image `media` with URL/image source | Lazy native image preview; click opens the source |
| File/media card | `file` or non-image `media` | Filename, MIME/media type, and external open action |
| Link preview | `scraped_link` | Preview image, title, description, and URL |
| Task card | `task` plus hydrated `object` | Status, title, description, owner, due date, and subtask count |
| Artifact card | `artifact` | Title, description, version, content type, and signed URL |
| Chart card | `chart.object.spec` | Bars, line, area, composed bar/line, scatter, pie, and treemap |
| Unknown/future attachment | `{id, type, ...}` | Visible generic card instead of silent filtering |

The web room does not currently render message-level native templates or
inline action attachments as interactive UI. The macOS app therefore keeps
those payloads visible as generic cards, but does not invent an execution
surface. When the persisted message wire and web renderer gain that contract,
the macOS switch can adopt the same typed component grammar.

Raw HTML is never executed. The GFM renderer treats unsupported HTML as text,
matching the web renderer's no-raw-HTML security boundary.
