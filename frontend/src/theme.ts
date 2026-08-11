import { createTheme } from '@mui/material/styles'

/**
 * "Laboratory instrument" — this is a measurement tool, so the UI reads like a
 * readout: near-black canvas, hairline rules, every number in mono, and colour
 * used ONLY to carry meaning. Spec §20 asks for a minimal professional
 * interface with neutral colours; the character comes from typography and
 * density rather than decoration.
 *
 * Colour is semantic, never ornamental:
 *   cyan  = live / active        green = passed
 *   red   = failed               amber = throttled or degraded
 * Nothing else is coloured, so a glance at the screen is unambiguous.
 */

export const C = {
  bg: '#0A0B0D',
  surface: '#111316',
  surfaceHi: '#171A1E',
  line: '#23272C',
  lineSoft: '#1A1D21',
  text: '#E7E9EB',
  dim: '#8A9199',
  faint: '#565D65',
  live: '#4CC9E8',
  pass: '#4CC38A',
  fail: '#E5484D',
  warn: '#E8A33D',
} as const

/** Run state → colour. One source of truth so nothing drifts. */
export const stateColor = (state: string): string => {
  switch (state) {
    case 'COMPLETED':
      return C.pass
    case 'FAILED':
    case 'CANCELLED':
      return C.fail
    case 'TIMED_OUT':
    case 'RATE_LIMITED':
      return C.warn
    case 'RUNNING':
    case 'PREPARING':
    case 'EVALUATING':
      return C.live
    default:
      return C.faint
  }
}

const mono = '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace'
const sans = 'Archivo, -apple-system, BlinkMacSystemFont, sans-serif'
const display = '"Instrument Serif", Georgia, serif'

export const fonts = { mono, sans, display }

export const theme = createTheme({
  palette: {
    mode: 'dark',
    background: { default: C.bg, paper: C.surface },
    primary: { main: C.live, contrastText: '#04121A' },
    success: { main: C.pass },
    error: { main: C.fail },
    warning: { main: C.warn },
    text: { primary: C.text, secondary: C.dim },
    divider: C.line,
  },
  shape: { borderRadius: 3 },
  typography: {
    fontFamily: sans,
    // Display face carries the page titles; everything else stays quiet.
    h1: { fontFamily: display, fontWeight: 400, fontSize: '2.9rem', letterSpacing: '-0.02em' },
    h2: { fontFamily: display, fontWeight: 400, fontSize: '2rem', letterSpacing: '-0.015em' },
    h3: { fontFamily: display, fontWeight: 400, fontSize: '1.5rem' },
    h6: { fontFamily: sans, fontWeight: 600, fontSize: '0.95rem', letterSpacing: '-0.01em' },
    // Section labels: small, tracked-out, uppercase — instrument panel legends.
    overline: {
      fontFamily: mono,
      fontSize: '0.68rem',
      fontWeight: 500,
      letterSpacing: '0.16em',
      textTransform: 'uppercase',
      color: C.faint,
      lineHeight: 2.2,
    },
    body2: { fontSize: '0.875rem', lineHeight: 1.6 },
    caption: { fontFamily: mono, fontSize: '0.75rem', color: C.dim },
    button: { textTransform: 'none', fontWeight: 600, letterSpacing: '0.01em' },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: C.bg,
          // Faint grain + a single cool wash from the top-left keeps a large
          // dark canvas from reading as flat black.
          backgroundImage: `radial-gradient(120rem 60rem at -10% -20%, rgba(76,201,232,0.05), transparent 60%)`,
          backgroundAttachment: 'fixed',
        },
        '::selection': { background: 'rgba(76,201,232,0.28)' },
        '*::-webkit-scrollbar': { width: 10, height: 10 },
        '*::-webkit-scrollbar-thumb': {
          background: C.line,
          border: `2px solid ${C.bg}`,
          borderRadius: 6,
        },
        '@keyframes asoPulse': {
          '0%,100%': { opacity: 1 },
          '50%': { opacity: 0.35 },
        },
        '@keyframes asoRise': {
          from: { opacity: 0, transform: 'translateY(6px)' },
          to: { opacity: 1, transform: 'none' },
        },
      },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: C.surface,
          border: `1px solid ${C.line}`,
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 3, paddingInline: 14 },
        outlined: { borderColor: C.line, '&:hover': { borderColor: C.dim } },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontFamily: mono, fontSize: '0.7rem', height: 22, borderRadius: 3 },
        outlined: { borderColor: C.line },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: C.lineSoft, paddingBlock: 10 },
        head: {
          fontFamily: mono,
          fontSize: '0.68rem',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: C.faint,
          borderColor: C.line,
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { height: 2, backgroundColor: C.lineSoft },
      },
    },
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { fontFamily: mono, fontSize: '0.85rem' },
        notchedOutline: { borderColor: C.line },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: C.surfaceHi,
          border: `1px solid ${C.line}`,
          fontFamily: mono,
          fontSize: '0.72rem',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { textTransform: 'none', minHeight: 42, fontWeight: 600, fontSize: '0.85rem' },
      },
    },
  },
})
