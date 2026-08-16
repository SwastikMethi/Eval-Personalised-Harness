import { motion } from 'motion/react'
import { respectMotion, rise } from '../design/motion'
import { Notice } from '../ui'
import StepRepository from './wizard/StepRepository'
import StepReview from './wizard/StepReview'
import StepStacks from './wizard/StepStacks'
import StepTasks from './wizard/StepTasks'
import { useWizard } from './wizard/useWizard'

/**
 * The four screens that set up a benchmark.
 *
 * Navigation lives in the rail, not here — the rail already renders the whole
 * sequence including Live and Results, and a second stepper inside the content
 * column would be the same information twice.
 */
export default function Wizard() {
  const w = useWizard()

  return (
    <div>
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
