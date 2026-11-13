# Design: OSINT Daily

The locked system. Every Hallmark run reads this first and pages share it. Change it on purpose; the file is the rule.

## System
- Genre: editorial
- Shape of the first page: app screen (Tracker, Feed, Timelines, Map share one shell)
- Theme: brand (mirrors the personal site: amber in dark, blue in light; Space Grotesk over Inter)
- Axes: light/grotesk-sans/chromatic-blue · posture: restrained

## Tokens
`css/tokens.css` is the source of truth; `site.css` (news pages) and `styles.css` (map) both import it. The project's own names, with the Hallmark role aliases:
```css
:root.light-mode {
  --bg0: oklch(98.3% 0.004 95);  --bg1: oklch(96.4% 0.007 100);  --bg2: oklch(93.8% 0.008 100);  /* --color-paper, -2, -3 */
  --bright: oklch(21% 0.006 95);  --text2: oklch(30.5% 0.01 115);  --text: oklch(50% 0.009 100);   /* --color-ink, -ink-2, -muted */
  --border: oklch(91.5% 0.005 95);                                                                  /* --color-rule */
  --accent: #2e86ff;  --accent-fill: oklch(52% 0.19 258);  --on-accent: oklch(99.4% 0.003 258);
  --accent2: #dc2626;  /* the one alarm colour */   --flag: #be185d;  /* the reader's own mark */
}
:root { /* dark default */ --bg0: oklch(16.5% 0.006 75); --accent: #f0a030; --accent2: #f26569; --flag: #ec5fa4; }
--font-display: 'Space Grotesk';  --font-body: 'Inter';  --font-mono: JetBrains Mono (code only)
--radius-sm: 4px;  --radius-md: 6px;  --radius-lg: 10px;  --radius-pill: 999px
```
The spacing scale (`--space-3xs` 2px to `--space-4xl` 144px), easings, durations and z levels live in `tokens.css`. No colour or font literal past the token block; padding, margin and gap use `--space-*`.

## Colour rule
Three hues, each with one job: `--accent` the reader's own state (tracked, active, selected, links), `--accent2` conflict and severity, `--flag` the bookmark. Colour never encodes how well sourced an item is. `--accent-fill` (not `--accent`) sits under text so white labels clear 4.5:1 in light mode.

## Type
- Labels, pills, meta, table heads: Inter, 11 to 12px, sentence case, untracked. No uppercase, no tracking, no mono as costume. Pipeline values arrive lowercase; `::first-letter` capitalises them.
- Nothing under 11px. Figures and dates take `font-variant-numeric: tabular-nums`.
- The `CHIRAG` wordmark is the only capitals on the site.

## Controls
- Primary: `--accent-fill`, `--on-accent` label, `--radius-sm`, 28 to 32px tall
- Secondary: hairline `--border2`, `--card` fill, same radius and height
- Focus: `outline: 2px solid var(--color-focus)`, instant; inputs inset (`outline-offset: -1px`), never a border change
- Disabled: opacity .55, `cursor: not-allowed`, the native attribute

## Surfaces
Hairline cards, no thick side stripes (state recolours the whole border). One edge per floating surface: a shadow or a border, never both. Solid nav on the page's paper, no glass.

## Motion
- Character: brisk. One scroll reveal (`.js .animate-on-scroll`, visible without script). `transform` and `opacity` only, never `transition: all`. Under reduced motion everything ends at once (global block in `tokens.css`).

## Exports
`css/tokens.css` in this project. Tailwind, DTCG or shadcn blocks are added here on request.
