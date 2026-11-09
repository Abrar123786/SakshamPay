# SakshamPay design system (P-7)

The UI foundation every later screen is built from. It covers design tokens, typography,
layout and a small set of components, and it targets WCAG 2.2 AA.

- Tokens: `frontend/src/styles/index.css` (Tailwind CSS v4 `@theme`, no `tailwind.config.js`)
- Components: `frontend/src/components/ui/` (import from `components/ui`)
- Page layout: `frontend/src/layouts/PageContainer.jsx`, `PageHeader.jsx`
- Live reference: **`/__ui`** on the development server (`npm run dev`, then
  http://localhost:5173/__ui). The gallery is **not part of production builds**.

## Principles

1. **Calm and trustworthy.** Use one brand colour, warm neutrals, borders instead of
   heavy shadows, and no decoration that competes with the payment information.
2. **Risk colour means risk.** LOW, MEDIUM and HIGH colours appear only in `RiskBadge`
   (and later risk-specific UI). Application errors use the separate `danger` tokens.
3. **Never colour alone.** Every status carries words, and risk levels also carry a
   distinct icon shape.
4. **Plain, small and reusable.** Components are thin wrappers over HTML elements and
   pass other props through (`...rest`). No component library, no CSS-in-JS, no variant
   helper package: a 1-line `cx()` joins class names.

## Colour tokens

Use tokens as Tailwind utilities, e.g. `bg-brand`, `text-ink-muted`, `border-line-input`.
Contrast ratios below are computed (WCAG 2.x formula) and enforced by
`src/design-system.test.js`. The minimum is 4.5:1 for text and 3:1 for form-control
outlines and focus indicators.

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `ink` | `#14181f` | Primary text | 16.46 on surface |
| `ink-muted` | `#4b5361` | Secondary text | 7.17 on surface |
| `ink-subtle` | `#5f6773` | Captions, placeholders | 5.29 on surface, 4.89 on surface-muted |
| `ink-disabled` | `#8a8f98` | Disabled text only | 3.25 (exempt: disabled) |
| `surface` | `#f7f6f3` | Page background | |
| `surface-raised` | `#ffffff` | Cards, inputs | |
| `surface-muted` | `#efede8` | Hover, disabled fields, skeletons | |
| `line` | `#e2e0da` | Decorative borders and dividers | 1.32 (decorative, exempt) |
| `line-strong` | `#c9c6be` | Stronger decorative borders | 1.71 (decorative, exempt) |
| `line-input` | `#8a867d` | Form-control and secondary-button outlines | 3.63 on white, 3.10 on surface-muted |
| `brand` | `#0f5c63` | Primary actions, links, focus ring | 7.69 white-on-brand, 7.11 on surface |
| `brand-hover` | `#0b4a50` | Primary hover | 9.95 white-on |
| `brand-soft` | `#e3eff0` | Tinted backgrounds | brand text 6.54 |
| `info`, `success` (+ `-soft`) | = `brand`, `brand-soft` | Info and success messages | as brand |
| `danger` | `#b42318` | Errors, destructive actions | 6.57 on white and white-on |
| `danger-hover` | `#912018` | Destructive hover | 8.66 white-on |
| `danger-soft` | `#fbe9e7` | Error backgrounds | danger text 5.61 |
| `danger-line` | `#e8a29b` | Error-alert border (decorative) | |
| `risk-low` / `risk-low-soft` | `#1d6b3a` / `#e6f2ea` | **RiskBadge only** | 5.68 |
| `risk-medium` / `risk-medium-soft` | `#8a5a00` / `#faf0dc` | **RiskBadge only** | 5.24 |
| `risk-high` / `risk-high-soft` | `#a3271f` / `#fbe9e7` | **RiskBadge only** | 6.25 |

**Why success is teal, not green:** a green "Saved" message next to a green LOW-risk badge
would suggest the payment was judged safe. Success and info therefore reuse the brand
teal, and there is no amber "warning" tone, so amber always means MEDIUM risk.

### Palette restriction (approved modification)

`index.css` resets Tailwind's **chromatic** default palettes (`red`, `orange`, `amber`,
`yellow`, `lime`, `green`, `emerald`, `teal`, `cyan`, `sky`, `blue`, `indigo`, `violet`,
`purple`, `fuchsia`, `pink`, `rose`), so classes like `bg-red-500` or `text-green-700`
produce no CSS. This means brand, error and risk colours can only come from the tokens.

The **neutral** ramps (`slate`, `gray`, `zinc`, `neutral`, `stone`) plus `black`, `white`
and `transparent` remain available for ordinary UI work. Prefer the semantic tokens
(`ink-*`, `surface-*`, `line-*`) when one fits. A test fails if any source file uses a
removed palette class, because such a class silently does nothing.

## Typography

**IBM Plex Sans** (variable, weights 100–700) is self-hosted through
`@fontsource-variable/ibm-plex-sans`. There are no third-party font requests (a test
checks this). The browser downloads only the subsets it needs: latin is about 46 KB,
and latin-ext (which contains ₹) is about 31 KB. Text renders in the system font until
Plex arrives (`font-display: swap`).

Plex digits are tabular by default, so amounts line up in columns without extra CSS.

| Class | Size / line height | Weight | Use |
| --- | --- | --- | --- |
| `text-4xl` | 36/40 | 600 | Hero headings |
| `text-3xl` | 30/36 | 600 | Page `h1` (`PageHeader`) |
| `text-2xl` | 24/32 | 600 | Section headings |
| `text-xl` | 20/28 | 600 | Sub-sections |
| `text-lg` | 18/28 | 400 | Lead paragraphs |
| `text-base` | 16/24 | 400 | Body, **all inputs** (prevents mobile zoom on focus) |
| `text-sm` | 14/20 | 400–500 | Labels, buttons, card text |
| `text-xs` | 12/16 | 500 | Badges, captions |

Each page has a single `h1` (`PageHeader`). Card titles default to `h2`; use
`titleAs="h3"` where the outline needs it.

**Money:** `formatINR(paise)` in `src/utils/format.js` takes **integer paise** and uses
Indian grouping: `formatINR(10000000)` gives `₹1,00,000.00`. It throws on non-integers,
so a rupee/paise mix-up fails loudly instead of showing a wrong amount.

## Spacing, radius, shadow, motion

- **Spacing:** Tailwind's 4 px scale. Card padding is `px-5 py-4`, gaps between fields
  are `gap-5`/`gap-6`, and sections are separated by `py-10`–`py-16`.
- **Radius:** `rounded-sm` for badges, `rounded-md` for buttons and inputs, `rounded-lg`
  for cards.
- **Shadow:** cards use borders, not shadows. `shadow-xs`…`shadow-lg` are tinted with
  `ink` and kept for overlays (menus, dialogs) in later phases.
- **Focus:** every focusable element shows a 2 px `brand` outline with a 2 px offset
  (global `:focus-visible`). Inputs put the ring on their frame via `focus-within`.
- **Motion:** only colour transitions and spinners. `prefers-reduced-motion` disables
  animations and transitions globally.

## Layout and breakpoints

Design from **360 px** up. Tailwind's default breakpoints are kept: `sm` 640, `md` 768,
`lg` 1024 and `xl` 1280.

`PageContainer` centres content with side padding of 16 px, then 24 px from `sm` and
32 px from `lg`.

| `size` | Max width | Use |
| --- | --- | --- |
| `narrow` | 576 px (`max-w-xl`) | Forms, payment and risk review |
| `default` | 1152 px (`max-w-6xl`) | Most pages |
| `wide` | 1280 px (`max-w-7xl`) | Data tables |

`PageHeader` renders an optional eyebrow, the page `h1`, a description and actions. It
stacks on mobile and switches to a row from `sm`.

## Components

| Component | Purpose | Accessibility notes |
| --- | --- | --- |
| `Button` | `variant`: primary, secondary, ghost, danger. `size`: sm 32 px, md 40 px, lg 48 px. Also `fullWidth`, `loading`, `leadingIcon`, `trailingIcon`, and `to` (renders a router link) | `type="button"` by default. `loading` sets `disabled` and `aria-busy` and keeps the label. Icons are `aria-hidden` |
| `IconButton` | Icon-only action | `label` is required: it becomes `aria-label` and `title`. Warns in development if it is missing |
| `Label` | Form label | `optional` appends "(optional)" in words |
| `Input` | Text input with optional `prefix`/`suffix` (e.g. ₹) and `endAction` (an interactive control inside the frame) | 16 px text, 3.63:1 outline. `invalid` sets `aria-invalid` and the danger border. `prefix`/`suffix` are `aria-hidden`; `endAction` is not |
| `PasswordInput` (P-8) | `Input` with a show/hide toggle | The toggle is a real button named "Show password" with `aria-pressed` and `aria-controls`. It never submits the form |
| `Field` | Label + control + hint + error | Generates ids and wires `htmlFor`, `aria-describedby` (hint, error), `aria-required` and `aria-invalid`. The child is a render function: `{(control) => <Input {...control} />}` |
| `Card`, `CardHeader`, `CardBody`, `CardFooter` | Bordered surface | Pair `aria-labelledby` with `CardHeader titleId` to make a named region. `titleAs` sets the heading level |
| `Badge` | Neutral, brand or danger label | **No risk tones** |
| `RiskBadge` | `level` LOW/MEDIUM/HIGH (case-insensitive), optional `score` | Words ("High risk") plus a distinct icon per level. The score is read as "score 75". An unknown level shows a neutral "Risk not available" badge, never a risk colour |
| `LoadingState` | Spinner with a visible label | `role="status"`, `aria-live="polite"` |
| `Skeleton` | Placeholder block | `aria-hidden`. Mark the loading container `aria-busy` |
| `ErrorState` | Failed request or section | `role="alert"`. Takes an `ApiError` (`error`) or a `message`, shows the request ID for support, and has an optional retry |
| `InlineAlert` | `tone`: info, success, danger, neutral | Danger uses `role="alert"`; the others use `role="status"` |
| `Spinner` | Decorative spinner | `aria-hidden`. Use `LoadingState` when the user needs to be told |

### Conventions

- **Don't override a property a component already sets.** Tailwind decides conflicts
  by CSS source order, not by the order of classes, so `className="py-3"` on a component
  that sets `py-4` may or may not win. Pass layout-only classes such as margins,
  `w-*` or grid placement, or add a prop when a real variant is needed. (P-7 removed
  two such conflicts: the disabled `Input` background and the `BackendStatus` header
  padding.)
- **Keep non-component exports out of component files** (the oxlint
  `only-export-components` rule supports Fast Refresh). Put helpers in `src/utils/`.
- **Pass through the native props.** Components spread `...rest` onto the underlying
  element, and React 19 passes `ref` as a normal prop, so no `forwardRef` is needed.
- **Use Lucide icons at 1.75 stroke width** (2 inside the small badges, so the
  icons stay legible at 14 px). Icons are always decorative (`aria-hidden`)
  unless they are the only content, in which case use `IconButton`.

## Development gallery (`/__ui`)

`src/pages/dev/UiGalleryPage.jsx` shows every token, type style, component and state.
`src/routes.jsx` registers it only when `import.meta.env.DEV` is true. Vite replaces
that flag with `false` in `npm run build`, so the lazy import and the page are removed
from the bundle.

In production, `/__ui` falls through to the 404 page. This was checked against
`vite preview`: the page showed "Page not found", only the main bundle was requested,
and the built JavaScript contains no gallery code.

## Tests

The tests use Vitest 4 with React Testing Library, jest-dom and user-event in jsdom.
Run them from `frontend/`:

```powershell
npm test            # run once
npm run test:watch  # re-run on save
```

| File | Covers |
| --- | --- |
| `src/utils/utils.test.js` | `cx`, `formatINR` (grouping, paise, rejects non-integers) |
| `src/components/ui/Button.test.jsx` | Button, IconButton, Spinner |
| `src/components/ui/Field.test.jsx` | Label, Input, Field wiring |
| `src/components/ui/display.test.jsx` | Card, Badge, RiskBadge |
| `src/components/ui/feedback.test.jsx` | LoadingState, Skeleton, ErrorState, InlineAlert |
| `src/layouts/layout.test.jsx` | PageContainer, PageHeader, AppLayout landmarks |
| `src/components/existing.test.jsx` | Regression: BackendStatus (mocked API), ErrorFallback, ErrorBoundary, NotFoundPage |
| `src/routes.test.jsx` | Route table, `/__ui` present only with dev routes |
| `src/design-system.test.js` | Guards: risk colours only in RiskBadge, palette restriction, token contrast, self-hosted font |

**npm 10.9 caveat:** adding or upgrading `vitest` with npm 10.9.x can crash with
`Cannot read properties of null (reading 'edgesOut')`, an npm bug triggered by Vitest's
optional peer dependencies. `npm install` and `npm ci` from the committed lockfile work
normally. To change the Vitest version, use npm 11:
`npx -y npm@11 install -D vitest@<version>`.

## Browser support and limitations

- **Tailwind CSS v4 needs modern browsers:** Safari 16.4+, Chrome 111+ and Firefox
  128+. Older browsers get unstyled or partly styled pages.
- **Disabled buttons use 60 % opacity.** Disabled controls are exempt from contrast
  requirements, but explain why an action is unavailable where it matters.
- **The landing page (`LandingPage.jsx`) is still the P-2 placeholder** and has not been
  rebuilt with these components. It keeps its own `px-6` padding on mobile until the
  real landing page is built.
- **No dark mode yet.** `color-scheme: light` is set explicitly.
- **Automated checks don't replace a manual review.** axe-core and keyboard checks
  passed, but a screen-reader pass (NVDA and VoiceOver) is still recommended once real
  screens exist.
