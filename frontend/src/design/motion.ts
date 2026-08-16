/**
 * Motion.
 *
 * The rule from the vault, and it is the difference between polish and
 * irritation: **animation communicates state, it never decorates.** No intro
 * sequences, no camera flights, and above all nothing that delays a number the
 * reader could already have. A benchmark result withheld for dramatic effect is
 * a worse product, not a nicer one.
 *
 * `prefers-reduced-motion` REMOVES movement rather than slowing it down. A slow
 * animation is more uncomfortable for a motion-sensitive reader than none, so
 * every variant below collapses to an instant state change.
 */

import type { Transition, Variants } from 'motion/react'

export const duration = { fast: 0.12, base: 0.18, slow: 0.32 } as const

/** Decelerating, slightly overshoot-free. Everything shares it so the app feels like one thing. */
export const ease = [0.2, 0.7, 0.3, 1] as const

export const transition: Transition = { duration: duration.base, ease }

/** True when the reader has asked the OS for less movement. */
export const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/**
 * Screen and panel entrance. A 6px rise, which reads as "this arrived" without
 * being a performance. Anything larger starts to feel like a slide deck.
 */
export const rise: Variants = {
  hidden: { opacity: 0, y: 6 },
  shown: { opacity: 1, y: 0, transition },
}

/** For lists where arrival order carries meaning — run states, timeline entries. */
export const stagger = (gap = 0.03): Variants => ({
  hidden: {},
  shown: { transition: { staggerChildren: gap } },
})

/**
 * A measured bar growing from zero. This one IS meaningful: it shows the value
 * being read off rather than asserted. Kept short so the number is legible
 * almost immediately.
 */
export const growBar = (pct: number): Variants => ({
  hidden: { scaleX: 0 },
  shown: { scaleX: pct / 100, transition: { duration: duration.slow, ease } },
})

/** Live-state heartbeat. Only ever applied to something genuinely in progress. */
export const beat: Variants = {
  shown: {
    opacity: [1, 0.25, 1],
    transition: { duration: 1.6, ease, repeat: Infinity },
  },
}

/**
 * Wrap any variant set so it becomes inert under reduced motion. Callers use
 * this instead of checking the media query themselves, so the behaviour cannot
 * drift between components.
 */
export const respectMotion = (variants: Variants): Variants =>
  prefersReducedMotion() ? { hidden: {}, shown: {} } : variants
