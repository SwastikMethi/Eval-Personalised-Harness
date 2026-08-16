/**
 * Typography.
 *
 * Three roles, and the pairing IS the identity: a serif for headings against
 * mono for every figure. This is a measurement tool, so it should read like an
 * instrument readout rather than a dashboard — the serif gives it a voice, the
 * mono makes the numbers trustworthy.
 *
 * The faces are the ones theme.ts already named. Webfonts are deliberately NOT
 * loaded: the app must render correctly offline and behind a strict CSP, and a
 * silent fallback to a metrically different face is worse than choosing a
 * system stack on purpose. Each stack leads with the best available local face
 * and degrades sensibly.
 */

export const font = {
  /** Every number, path, id, command and status label. */
  mono: '"IBM Plex Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
  /** Interface text: labels, prose, controls. */
  sans: 'Archivo, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
  /** Screen titles and headline figures only. Used sparingly, so it stays an event. */
  serif: '"Instrument Serif", "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif',
} as const

/**
 * Type scale. Sizes in px with their intended line-height, so a component never
 * has to guess. `display` is for one number per screen at most.
 */
export const type = {
  display: { fontFamily: font.serif, fontSize: 66, lineHeight: 1, letterSpacing: '-.03em' },
  title: { fontFamily: font.serif, fontSize: 33, lineHeight: 1.15, letterSpacing: '-.01em' },
  heading: { fontFamily: font.serif, fontSize: 21, lineHeight: 1.25 },
  subheading: { fontFamily: font.serif, fontSize: 17, lineHeight: 1.3 },

  body: { fontFamily: font.sans, fontSize: 14, lineHeight: 1.55 },
  bodySm: { fontFamily: font.sans, fontSize: 13, lineHeight: 1.5 },

  /** Uppercase section markers and field labels. */
  label: {
    fontFamily: font.mono,
    fontSize: 10.5,
    lineHeight: 1.4,
    letterSpacing: '.12em',
    textTransform: 'uppercase' as const,
  },

  /** Any figure that shares a column with another figure. */
  data: {
    fontFamily: font.mono,
    fontSize: 13,
    lineHeight: 1.5,
    fontVariantNumeric: 'tabular-nums' as const,
  },
  dataLg: {
    fontFamily: font.mono,
    fontSize: 26,
    lineHeight: 1.1,
    letterSpacing: '-.02em',
    fontVariantNumeric: 'tabular-nums' as const,
  },
  caption: { fontFamily: font.mono, fontSize: 11, lineHeight: 1.5, color: 'inherit' },
} as const

/** Running prose should not exceed this, per the vault's readability rule. */
export const measure = '64ch'
