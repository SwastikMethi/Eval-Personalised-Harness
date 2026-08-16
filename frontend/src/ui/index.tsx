/**
 * UI primitives.
 *
 * These replace MUI. Dropping a component library means its accessibility work
 * leaves with it, so focus rings, keyboard paths, labelling and focus-trapping
 * are built in here deliberately rather than assumed — the vault is explicit
 * that they must be ported on purpose.
 *
 * Everything styles through the design tokens. No component invents a colour.
 */

import { motion } from 'motion/react'
import type { CSSProperties, ReactNode } from 'react'
import { useEffect, useId, useRef } from 'react'

import { color, elevation, radius, space, tint } from '../design/tokens'
import { font, type } from '../design/typography'
import { beat, respectMotion, rise, transition } from '../design/motion'

type Tone = 'live' | 'pass' | 'fail' | 'warn' | 'idle'

const toneColor: Record<Tone, string> = {
  live: color.live,
  pass: color.pass,
  fail: color.fail,
  warn: color.warn,
  idle: color.faint,
}
const toneBg: Record<Tone, string> = {
  live: tint.live,
  pass: tint.pass,
  fail: tint.fail,
  warn: tint.warn,
  idle: 'transparent',
}
const toneEdge: Record<Tone, string> = {
  live: tint.liveEdge,
  pass: tint.passEdge,
  fail: tint.failEdge,
  warn: tint.warnEdge,
  idle: color.line,
}

/** Applied to every interactive element. One ring, everywhere, always visible. */
const focusRing: CSSProperties = { outline: 'none' }
const focusCss = `
  .aso-focusable:focus-visible {
    outline: 2px solid ${color.live};
    outline-offset: 2px;
  }
  .aso-inset-focus:focus-visible {
    outline: 2px solid ${color.live};
    outline-offset: -2px;
  }
`

/** Injected once. Pseudo-classes cannot be expressed as inline styles. */
export function UIStyles() {
  return (
    <style>{`
      ${focusCss}
      .aso-hover-line:hover { border-color: ${color.faint}; }
      .aso-scroll-x { overflow-x: auto; }
      @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after { animation-duration: .001ms !important; transition-duration: .001ms !important; }
      }
    `}</style>
  )
}

/* ── Text ──────────────────────────────────────────────────────────────── */

export function Label({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ ...type.label, color: color.faint, ...style }}>{children}</div>
}

const inkColor = {
  text: color.text,
  dim: color.dim,
  faint: color.faint,
  ...toneColor,
} as const

export function Mono({
  children,
  tone = 'text',
  size = 13,
  style,
}: {
  children: ReactNode
  tone?: keyof typeof inkColor
  size?: number
  style?: CSSProperties
}) {
  const c = inkColor[tone]
  return (
    <span
      style={{
        fontFamily: font.mono,
        fontSize: size,
        fontVariantNumeric: 'tabular-nums',
        color: c,
        ...style,
      }}
    >
      {children}
    </span>
  )
}

/* ── Panel ─────────────────────────────────────────────────────────────── */

export function Panel({
  label,
  action,
  children,
  accent,
  style,
}: {
  label?: ReactNode
  action?: ReactNode
  children: ReactNode
  accent?: boolean
  style?: CSSProperties
}) {
  return (
    <motion.section
      variants={respectMotion(rise)}
      initial="hidden"
      animate="shown"
      style={{
        background: color.surface,
        border: `1px solid ${accent ? tint.liveEdge : color.line}`,
        borderRadius: radius.md,
        padding: space[5],
        marginBottom: space[4],
        boxShadow: accent ? elevation.glow : undefined,
        ...style,
      }}
    >
      {(label || action) && (
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: space[4],
            marginBottom: space[4],
          }}
        >
          {label ? <Label>{label}</Label> : <span />}
          {action}
        </header>
      )}
      {children}
    </motion.section>
  )
}

/* ── Status ────────────────────────────────────────────────────────────── */

export function Status({
  tone = 'idle',
  pulse,
  children,
}: {
  tone?: Tone
  pulse?: boolean
  children: ReactNode
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: font.mono,
        fontSize: 11,
        letterSpacing: '.04em',
        padding: '3px 9px',
        borderRadius: radius.pill,
        border: `1px solid ${toneEdge[tone]}`,
        background: toneBg[tone],
        color: toneColor[tone],
        whiteSpace: 'nowrap',
      }}
    >
      <motion.span
        variants={pulse ? respectMotion(beat) : undefined}
        animate={pulse ? 'shown' : undefined}
        style={{
          width: 5,
          height: 5,
          borderRadius: '50%',
          background: 'currentColor',
          flex: 'none',
        }}
      />
      {children}
    </span>
  )
}

/* ── Button ────────────────────────────────────────────────────────────── */

export function Button({
  children,
  onClick,
  variant = 'default',
  size = 'md',
  disabled,
  type: htmlType = 'button',
  title,
  style,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'default' | 'primary' | 'danger' | 'ghost'
  size?: 'sm' | 'md'
  disabled?: boolean
  type?: 'button' | 'submit'
  title?: string
  style?: CSSProperties
}) {
  const base: CSSProperties = {
    ...focusRing,
    fontFamily: font.sans,
    fontSize: size === 'sm' ? 12 : 13,
    fontWeight: 500,
    padding: size === 'sm' ? '4px 10px' : '9px 16px',
    borderRadius: radius.md,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
    border: `1px solid ${color.line}`,
    background: color.raised,
    color: color.text,
    transition: `border-color ${transition.duration}s, background ${transition.duration}s`,
  }
  const variants: Record<string, CSSProperties> = {
    default: {},
    primary: {
      background: color.live,
      borderColor: color.live,
      color: color.onLive,
      fontWeight: 600,
    },
    danger: { background: 'transparent', borderColor: tint.failEdge, color: color.fail },
    ghost: { background: 'transparent', borderColor: 'transparent', color: color.dim },
  }
  return (
    <button
      className="aso-focusable aso-hover-line"
      type={htmlType}
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {children}
    </button>
  )
}

/* ── Field ─────────────────────────────────────────────────────────────── */

export function Field({
  label,
  value,
  onChange,
  placeholder,
  mono = true,
  type: inputType = 'text',
  min,
  disabled,
  hint,
}: {
  label: string
  value: string | number
  onChange: (v: string) => void
  placeholder?: string
  mono?: boolean
  type?: 'text' | 'number'
  min?: number
  disabled?: boolean
  hint?: ReactNode
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} style={{ ...type.label, color: color.faint, display: 'block', marginBottom: 6 }}>
        {label}
      </label>
      <input
        id={id}
        className="aso-focusable"
        type={inputType}
        min={min}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%',
          background: color.bg,
          border: `1px solid ${color.line}`,
          borderRadius: radius.md,
          color: color.text,
          fontFamily: mono ? font.mono : font.sans,
          fontSize: 13.5,
          padding: '10px 12px',
          opacity: disabled ? 0.5 : 1,
        }}
      />
      {hint && (
        <div style={{ ...type.caption, color: color.faint, marginTop: 5 }}>{hint}</div>
      )}
    </div>
  )
}

/* ── Check ─────────────────────────────────────────────────────────────── */

/**
 * A checkbox with its label wired through htmlFor/id.
 *
 * MUI's FormControlLabel did this association for us; hand-rolled checkboxes
 * routinely lose it, and a checkbox with no accessible name is invisible to a
 * screen reader and untestable by label. Hence the explicit useId.
 */
export function Check({
  checked,
  onChange,
  label,
  hint,
  disabled,
  align = 'center',
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
  hint?: ReactNode
  disabled?: boolean
  align?: 'center' | 'start'
}) {
  const id = useId()
  return (
    <div style={{ display: 'flex', gap: space[3], alignItems: align, padding: '3px 0' }}>
      <input
        id={id}
        className="aso-focusable"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        style={{
          accentColor: color.live,
          width: 14,
          height: 14,
          marginTop: align === 'start' ? 3 : 0,
          flex: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      />
      <label
        htmlFor={id}
        style={{
          minWidth: 0,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
        }}
      >
        {label}
        {hint && <div style={{ ...type.caption, color: color.faint }}>{hint}</div>}
      </label>
    </div>
  )
}

/* ── Segmented ─────────────────────────────────────────────────────────── */

/** Exclusive choice between a few options. Real buttons, so they are reachable. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode; disabled?: boolean }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div
      style={{
        display: 'inline-flex',
        flexWrap: 'wrap',
        border: `1px solid ${color.line}`,
        borderRadius: radius.md,
        overflow: 'hidden',
      }}
    >
      {options.map((o, i) => {
        const on = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            className="aso-inset-focus"
            aria-pressed={on}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            style={{
              ...focusRing,
              fontFamily: font.sans,
              fontSize: 12.5,
              fontWeight: on ? 600 : 400,
              padding: '7px 14px',
              border: 0,
              borderLeft: i === 0 ? 0 : `1px solid ${color.line}`,
              background: on ? color.raised : 'transparent',
              color: o.disabled ? color.faint : on ? color.text : color.dim,
              cursor: o.disabled ? 'not-allowed' : 'pointer',
              opacity: o.disabled ? 0.55 : 1,
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/* ── TextArea ──────────────────────────────────────────────────────────── */

export function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  rows?: number
}) {
  const id = useId()
  return (
    <div>
      <label
        htmlFor={id}
        style={{ ...type.label, color: color.faint, display: 'block', marginBottom: 6 }}
      >
        {label}
      </label>
      <textarea
        id={id}
        className="aso-focusable"
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%',
          background: color.bg,
          border: `1px solid ${color.line}`,
          borderRadius: radius.md,
          color: color.text,
          fontFamily: font.sans,
          fontSize: 13.5,
          padding: '10px 12px',
          resize: 'vertical',
        }}
      />
    </div>
  )
}

/* ── Output ────────────────────────────────────────────────────────────── */

/** Captured stdout/stderr. "exit 2" alone is undiagnosable. */
export function Output({ children }: { children: ReactNode }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: space[3],
        maxHeight: 260,
        overflow: 'auto',
        background: color.bg,
        border: `1px solid ${color.lineSoft}`,
        borderRadius: radius.sm,
        fontFamily: font.mono,
        fontSize: 11.5,
        lineHeight: 1.5,
        color: color.dim,
        whiteSpace: 'pre-wrap',
      }}
    >
      {children}
    </pre>
  )
}

/* ── Notice ────────────────────────────────────────────────────────────── */

export function Notice({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'warn' | 'fail'
  children: ReactNode
}) {
  const map = {
    info: { edge: color.line, bg: color.raised, fg: color.dim, icon: color.live, mark: 'i' },
    warn: { edge: tint.warnEdge, bg: tint.warn, fg: '#E9C68C', icon: color.warn, mark: '!' },
    fail: { edge: tint.failEdge, bg: tint.fail, fg: '#EFA1A4', icon: color.fail, mark: '✕' },
  }[tone]
  return (
    <div
      role={tone === 'info' ? undefined : 'status'}
      style={{
        display: 'grid',
        gridTemplateColumns: '16px 1fr',
        gap: space[3],
        padding: `${space[3]}px ${space[4]}px`,
        borderRadius: radius.md,
        border: `1px solid ${map.edge}`,
        background: map.bg,
        color: map.fg,
        fontSize: 13,
        marginBottom: space[3],
      }}
    >
      <span style={{ fontFamily: font.mono, color: map.icon }}>{map.mark}</span>
      <span>{children}</span>
    </div>
  )
}

/* ── Metric ────────────────────────────────────────────────────────────── */

export function Metric({
  label,
  value,
  unit,
  tone,
  sub,
}: {
  label: string
  value: ReactNode
  unit?: string
  tone?: Tone
  sub?: ReactNode
}) {
  return (
    <div>
      <Label>{label}</Label>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 2 }}>
        <span style={{ ...type.dataLg, color: tone ? toneColor[tone] : color.text }}>{value}</span>
        {unit && <span style={{ ...type.caption, color: color.faint }}>{unit}</span>}
      </div>
      {sub && <div style={{ ...type.caption, color: color.faint, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

/* ── Bar ───────────────────────────────────────────────────────────────── */

export function Bar({
  who,
  pct,
  value,
  muted,
}: {
  who: ReactNode
  pct: number
  value: ReactNode
  muted?: boolean
}) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(120px, 210px) 1fr 52px',
        gap: space[3],
        alignItems: 'center',
      }}
    >
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 12,
          color: color.dim,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {who}
      </span>
      <div
        style={{
          height: 6,
          background: color.lineSoft,
          borderRadius: radius.pill,
          overflow: 'hidden',
        }}
      >
        <motion.div
          initial={{ scaleX: 0 }}
          animate={{ scaleX: clamped / 100 }}
          transition={{ duration: 0.32, ease: [0.2, 0.7, 0.3, 1] }}
          style={{
            height: '100%',
            transformOrigin: 'left',
            borderRadius: radius.pill,
            background: muted ? color.line : color.live,
          }}
        />
      </div>
      <span style={{ ...type.data, fontSize: 12.5, textAlign: 'right' }}>{value}</span>
    </div>
  )
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */

export function Tabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: string[]
  active: string
  onSelect: (t: string) => void
}) {
  return (
    <div
      role="tablist"
      style={{ display: 'flex', gap: space[1], borderBottom: `1px solid ${color.line}`, marginBottom: space[4] }}
    >
      {tabs.map((t) => {
        const on = t === active
        return (
          <button
            key={t}
            className="aso-inset-focus"
            role="tab"
            aria-selected={on}
            onClick={() => onSelect(t)}
            style={{
              ...focusRing,
              background: 'none',
              border: 0,
              borderBottom: `2px solid ${on ? color.live : 'transparent'}`,
              color: on ? color.text : color.faint,
              fontFamily: font.sans,
              fontSize: 13,
              padding: '8px 14px',
              marginBottom: -1,
              cursor: 'pointer',
            }}
          >
            {t}
          </button>
        )
      })}
    </div>
  )
}

/* ── Empty ─────────────────────────────────────────────────────────────── */

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        color: color.faint,
        fontSize: 13,
        padding: `${space[5]}px 0`,
        textAlign: 'center',
      }}
    >
      {children}
    </div>
  )
}

/* ── Dialog ────────────────────────────────────────────────────────────── */

export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()

  // Escape closes, and focus is trapped inside — both are behaviours MUI used
  // to provide and that a hand-rolled dialog silently loses.
  useEffect(() => {
    if (!open) return
    const node = ref.current
    node?.querySelector<HTMLElement>('button, [href], input, select, textarea')?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return onClose()
      if (e.key !== 'Tab' || !node) return
      const items = [
        ...node.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ]
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(6,7,9,.72)',
        display: 'grid',
        placeItems: 'center',
        padding: space[5],
        zIndex: 50,
      }}
    >
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        variants={respectMotion(rise)}
        initial="hidden"
        animate="shown"
        style={{
          background: color.surface,
          border: `1px solid ${color.line}`,
          borderRadius: radius.lg,
          boxShadow: elevation.lift,
          padding: space[5],
          width: 'min(560px, 100%)',
          maxHeight: '84vh',
          overflowY: 'auto',
        }}
      >
        <h2 id={titleId} style={{ ...type.heading, margin: `0 0 ${space[4]}px`, fontWeight: 400 }}>
          {title}
        </h2>
        {children}
        {footer && (
          <div style={{ display: 'flex', gap: space[2], justifyContent: 'flex-end', marginTop: space[5] }}>
            {footer}
          </div>
        )}
      </motion.div>
    </div>
  )
}

/* ── Layout helpers ────────────────────────────────────────────────────── */

export function Row({
  children,
  gap = space[3],
  style,
}: {
  children: ReactNode
  gap?: number
  style?: CSSProperties
}) {
  return (
    <div style={{ display: 'flex', gap, alignItems: 'center', flexWrap: 'wrap', ...style }}>
      {children}
    </div>
  )
}

export function Grid({
  cols,
  min,
  children,
  gap = space[4],
}: {
  cols?: number
  min?: number
  children: ReactNode
  gap?: number
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: min
          ? `repeat(auto-fill, minmax(${min}px, 1fr))`
          : `repeat(${cols ?? 2}, minmax(0, 1fr))`,
        gap,
      }}
    >
      {children}
    </div>
  )
}

/** Wide content scrolls inside its own container so the page never does. */
export function ScrollX({ children }: { children: ReactNode }) {
  return <div className="aso-scroll-x">{children}</div>
}
