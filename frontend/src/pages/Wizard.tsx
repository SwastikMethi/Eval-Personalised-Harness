import { motion } from 'motion/react'
import { color, radius, space } from '../design/tokens'
import { respectMotion, rise } from '../design/motion'
import { measure, font, type } from '../design/typography'
import { Notice } from '../ui'
import StepRepository from './wizard/StepRepository'
import StepReview from './wizard/StepReview'
import StepStacks from './wizard/StepStacks'
import StepTasks from './wizard/StepTasks'
import { STEPS, useWizard, type Step } from './wizard/useWizard'

/**
 * The four screens that set up a benchmark, and the rail that moves between
 * them. Each screen is its own file; this holds only the shared state (via
 * useWizard) and the navigation.
 *
 * Numbering the stages is not decoration here — the steps genuinely are a
 * sequence, and later ones are unreachable until earlier ones produce something.
 */
export default function Wizard() {
  const w = useWizard()

  return (
    <div>
      <motion.header
        variants={respectMotion(rise)}
        initial="hidden"
        animate="shown"
        style={{ marginBottom: space[5] }}
      >
        <h1 style={{ ...type.title, fontWeight: 400, marginBottom: space[2] }}>
          New benchmark run
        </h1>
        <p style={{ ...type.body, color: color.dim, maxWidth: measure }}>
          Point it at a repository, pick what the agents should attempt, then choose which harness ×
          model combinations to compare.
        </p>
      </motion.header>

      <nav
        aria-label="Setup stages"
        style={{
          display: 'flex',
          gap: space[1],
          flexWrap: 'wrap',
          marginBottom: space[5],
          borderBottom: `1px solid ${color.line}`,
          paddingBottom: space[4],
        }}
      >
        {STEPS.map((label, i) => {
          const done = i < w.step
          const here = i === w.step
          return (
            <button
              key={label}
              type="button"
              className="aso-focusable"
              aria-current={here ? 'step' : undefined}
              disabled={!done && !here}
              onClick={() => done && w.setStep(i as Step)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space[2],
                padding: `6px ${space[3]}px`,
                borderRadius: radius.pill,
                border: `1px solid ${here ? color.line : 'transparent'}`,
                background: here ? color.raised : 'transparent',
                color: here ? color.text : done ? color.dim : color.faint,
                cursor: done ? 'pointer' : 'default',
                fontFamily: font.sans,
                fontSize: 13,
                fontWeight: here ? 600 : 400,
              }}
            >
              <span
                style={{
                  ...type.caption,
                  width: 18,
                  height: 18,
                  lineHeight: '18px',
                  textAlign: 'center',
                  borderRadius: '50%',
                  background: here ? color.live : done ? color.line : 'transparent',
                  color: here ? color.onLive : done ? color.text : color.faint,
                  border: here || done ? 'none' : `1px solid ${color.line}`,
                  flex: 'none',
                }}
              >
                {done ? '✓' : i + 1}
              </span>
              {label}
            </button>
          )
        })}
      </nav>

      {w.error && <Notice tone="fail">{w.error}</Notice>}

      <motion.div key={w.step} variants={respectMotion(rise)} initial="hidden" animate="shown">
        {w.step === 0 && <StepRepository w={w} />}
        {w.step === 1 && <StepTasks w={w} />}
        {w.step === 2 && <StepStacks w={w} />}
        {w.step === 3 && <StepReview w={w} />}
      </motion.div>
    </div>
  )
}
