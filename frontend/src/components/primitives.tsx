import { Box, Chip, Paper, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { C, fonts, stateColor } from '../theme'

/** Section container. Hairline border + a mono legend, like a panel on an instrument. */
export function Panel({
  label,
  action,
  children,
  sx,
}: {
  label?: string
  action?: ReactNode
  children: ReactNode
  sx?: object
}) {
  return (
    <Paper sx={{ p: 2.5, ...sx }}>
      {(label || action) && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            mb: 1.5,
            gap: 2,
          }}
        >
          {label && <Typography variant="overline">{label}</Typography>}
          {action}
        </Box>
      )}
      {children}
    </Paper>
  )
}

/** A labelled number. Values are mono so columns align and digits don't jitter. */
export function Stat({
  label,
  value,
  unit,
  color,
  hint,
}: {
  label: string
  value: ReactNode
  unit?: string
  color?: string
  hint?: string
}) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography
        sx={{
          fontFamily: fonts.mono,
          fontSize: '0.64rem',
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: C.faint,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5 }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: '1.35rem',
            fontWeight: 500,
            color: color ?? C.text,
            lineHeight: 1.3,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {value}
        </Typography>
        {unit && (
          <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.72rem', color: C.faint }}>
            {unit}
          </Typography>
        )}
      </Box>
      {hint && (
        <Typography sx={{ fontFamily: fonts.mono, fontSize: '0.66rem', color: C.faint }}>
          {hint}
        </Typography>
      )}
    </Box>
  )
}

/** Run state pill. Active states pulse so a live screen reads at a glance. */
export function StateChip({ state, size = 'small' }: { state: string; size?: 'small' | 'medium' }) {
  const color = stateColor(state)
  const active = ['RUNNING', 'PREPARING', 'EVALUATING'].includes(state)
  return (
    <Chip
      size={size}
      label={state.toLowerCase().replace('_', ' ')}
      variant="outlined"
      sx={{
        color,
        borderColor: `${color}55`,
        backgroundColor: `${color}12`,
        fontWeight: 500,
        ...(active && { animation: 'asoPulse 1.6s ease-in-out infinite' }),
      }}
    />
  )
}

/** Inline monospace value. */
export function Mono({
  children,
  color,
  size = '0.8rem',
}: {
  children: ReactNode
  color?: string
  size?: string
}) {
  return (
    <Box
      component="span"
      sx={{
        fontFamily: fonts.mono,
        fontSize: size,
        color: color ?? C.dim,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {children}
    </Box>
  )
}

/** Page heading in the display face, with an optional standfirst. */
export function PageTitle({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 3,
        mb: 3,
        animation: 'asoRise 400ms ease both',
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h2" sx={{ color: C.text }}>
          {title}
        </Typography>
        {sub && (
          <Typography sx={{ color: C.dim, fontSize: '0.9rem', mt: 0.5, maxWidth: '62ch' }}>
            {sub}
          </Typography>
        )}
      </Box>
      {action}
    </Box>
  )
}

/** Honest empty state — says what to do next rather than just "no data". */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <Typography sx={{ color: C.faint, fontSize: '0.85rem', fontStyle: 'italic', py: 1 }}>
      {children}
    </Typography>
  )
}
