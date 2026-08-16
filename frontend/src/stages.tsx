/* eslint-disable react/only-export-components -- the provider and its hooks
   belong together; splitting them would put the context in a third file that
   neither side reads on its own. */
import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

/**
 * Where you are in the benchmark, shared between the rail and the screens.
 *
 * The rail has to render the same progress the wizard is holding, and the two
 * live on opposite sides of the router. Only the position lives here — every
 * other piece of wizard state stays in useWizard, because nothing outside the
 * wizard needs it.
 */

export const WIZARD_STAGES = ['Repository', 'Tasks', 'Agent Stacks', 'Review'] as const

export type StageState = 'done' | 'current' | 'available' | 'locked'

interface StageValue {
  step: number
  setStep: (n: number) => void
  /** Highest step reached, so you can jump back and forward again freely. */
  furthest: number
  /** Live and Results are tabs of one screen; this says which is showing. */
  onResults: boolean
  setOnResults: (b: boolean) => void
}

const Ctx = createContext<StageValue | null>(null)

export function StageProvider({ children }: { children: ReactNode }) {
  const [step, setStepRaw] = useState(0)
  const [furthest, setFurthest] = useState(0)
  const [onResults, setOnResults] = useState(false)

  const value = useMemo<StageValue>(
    () => ({
      step,
      furthest,
      onResults,
      setOnResults,
      setStep: (n) => {
        setStepRaw(n)
        setFurthest((f) => Math.max(f, n))
      },
    }),
    [step, furthest, onResults],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/**
 * Screens read and move the position through this. It tolerates a missing
 * provider so a screen can still be rendered on its own in a test.
 */
export function useStage(): StageValue {
  const ctx = useContext(Ctx)
  const [fallbackStep, setFallbackStep] = useState(0)
  const [fallbackResults, setFallbackResults] = useState(false)
  const fallback = useMemo<StageValue>(
    () => ({
      step: fallbackStep,
      furthest: fallbackStep,
      setStep: setFallbackStep,
      onResults: fallbackResults,
      setOnResults: setFallbackResults,
    }),
    [fallbackStep, fallbackResults],
  )
  return ctx ?? fallback
}

export interface StageRow {
  label: string
  state: StageState
  go?: () => void
}

/** The six rows the rail draws, derived from the URL and the shared position. */
export function useStages(): { stages: StageRow[] } {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { step, furthest, onResults, setStep, setOnResults } = useStage()

  const onWizard = pathname.startsWith('/new')
  const onExperiment = pathname.startsWith('/experiments/') || pathname.startsWith('/runs/')

  const wizard: StageRow[] = WIZARD_STAGES.map((label, i) => {
    if (onExperiment) return { label, state: 'done' as StageState }
    if (!onWizard) {
      // From Overview only the first stage is meaningful — it starts a run.
      return i === 0
        ? { label, state: 'available' as StageState, go: () => navigate('/new') }
        : { label, state: 'locked' as StageState }
    }
    const state: StageState =
      i === step ? 'current' : i < step ? 'done' : i <= furthest ? 'available' : 'locked'
    return { label, state, go: i <= furthest ? () => setStep(i) : undefined }
  })

  const live: StageRow = {
    label: 'Live',
    state: onExperiment ? (onResults ? 'done' : 'current') : 'locked',
    go: onExperiment ? () => setOnResults(false) : undefined,
  }
  const results: StageRow = {
    label: 'Results',
    state: onExperiment ? (onResults ? 'current' : 'available') : 'locked',
    go: onExperiment ? () => setOnResults(true) : undefined,
  }

  return { stages: [...wizard, live, results] }
}
