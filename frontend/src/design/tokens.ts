/**
 * Design tokens — the single source of truth for every visual decision.
 *
 * The palette is lifted verbatim from the old `theme.ts` and deliberately
 * unchanged. It already did the hard part: colour here is SEMANTIC and never
 * ornamental, so a glance at a screen is unambiguous.
 *
 *   live  = running / active      pass = succeeded
 *   fail  = failed                warn = degraded, throttled, provisional
 *
 * Nothing else is coloured. A rebuild that reassigned these would force every
 * existing user to relearn the status vocabulary for no gain, so the visual
 * change comes from type, space and motion instead.
 *
 * What IS new is everything around colour — space, radii, elevation, glow —
 * which the old file lacked, leaving each component to invent its own values.
 * These are plain objects rather than a framework theme so the primitives stay
 * framework-free and MUI can be removed without touching them.
 */

export const color = {
  bg: '#0A0B0D',
  surface: '#111316',
  raised: '#171A1E',
  line: '#23272C',
  lineSoft: '#1A1D21',

  text: '#E7E9EB',
  dim: '#8A9199',
  faint: '#565D65',

  live: '#4CC9E8',
  pass: '#4CC38A',
  fail: '#E5484D',
  warn: '#E8A33D',

  /** Readable foreground on a solid `live` fill. */
  onLive: '#06232B',
} as const

export type ColorToken = keyof typeof color

/** Translucent companions, for tinted backgrounds and rings. */
export const tint = {
  live: 'rgba(76,201,232,.08)',
  pass: 'rgba(76,195,138,.08)',
  fail: 'rgba(229,72,77,.08)',
  warn: 'rgba(232,163,61,.08)',
  liveEdge: 'rgba(76,201,232,.30)',
  passEdge: 'rgba(76,195,138,.30)',
  failEdge: 'rgba(229,72,77,.30)',
  warnEdge: 'rgba(232,163,61,.30)',
} as const

/** 4px base. Referenced as space[3] rather than a raw pixel value. */
export const space = [0, 4, 8, 12, 16, 24, 32, 48, 64, 96] as const

export const radius = { sm: 4, md: 6, lg: 10, pill: 100 } as const

export const elevation = {
  /** Focus and active-experiment emphasis. The only glow in the system. */
  glow: '0 0 0 1px rgba(76,201,232,.28), 0 0 28px -8px rgba(76,201,232,.45)',
  lift: '0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6)',
} as const

/**
 * Run state → colour. One source of truth so nothing drifts, carried over
 * from theme.ts because the mapping is product knowledge, not styling.
 */
export const stateColor = (state: string): string => {
  switch (state) {
    case 'COMPLETED':
      return color.pass
    case 'FAILED':
    case 'CANCELLED':
      return color.fail
    case 'TIMED_OUT':
    case 'RATE_LIMITED':
      return color.warn
    case 'RUNNING':
    case 'PREPARING':
    case 'EVALUATING':
      return color.live
    default:
      return color.faint
  }
}

/** Which pill tone a run state should wear. */
export const stateTone = (state: string): 'live' | 'pass' | 'fail' | 'warn' | 'idle' => {
  switch (state) {
    case 'COMPLETED':
      return 'pass'
    case 'FAILED':
    case 'CANCELLED':
      return 'fail'
    case 'TIMED_OUT':
    case 'RATE_LIMITED':
      return 'warn'
    case 'RUNNING':
    case 'PREPARING':
    case 'EVALUATING':
      return 'live'
    default:
      return 'idle'
  }
}
