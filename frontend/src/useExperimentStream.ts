import { useEffect, useRef, useState } from 'react'
import type { Progress } from './api'
import { eventsUrl } from './api'

export interface RunEventLine {
  run_id: string
  type: string
  payload: Record<string, unknown>
  at: string
}

/**
 * Live experiment state over SSE.
 *
 * The backend replays persisted events on connect, so opening this page late —
 * or after a refresh — still shows the full history rather than starting blank.
 * Falls back to nothing if EventSource errors; the caller keeps the last
 * snapshot and can poll `/progress` instead.
 */
export function useExperimentStream(experimentId: string | undefined) {
  const [progress, setProgress] = useState<Progress | null>(null)
  const [events, setEvents] = useState<RunEventLine[]>([])
  const [connected, setConnected] = useState(false)
  const [finished, setFinished] = useState(false)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!experimentId) return
    setProgress(null)
    setEvents([])
    setFinished(false)

    const source = new EventSource(eventsUrl(experimentId))
    sourceRef.current = source

    source.addEventListener('open', () => setConnected(true))
    source.addEventListener('progress', (e) => {
      setConnected(true)
      try {
        setProgress(JSON.parse((e as MessageEvent).data) as Progress)
      } catch {
        /* ignore a malformed frame rather than tearing down the stream */
      }
    })
    source.addEventListener('run', (e) => {
      try {
        const line = JSON.parse((e as MessageEvent).data) as RunEventLine
        // Newest first, and bounded so a long experiment cannot grow forever.
        setEvents((prev) => [line, ...prev].slice(0, 300))
      } catch {
        /* ignore */
      }
    })
    source.addEventListener('done', () => {
      setFinished(true)
      source.close()
      setConnected(false)
    })
    source.addEventListener('error', () => setConnected(false))

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [experimentId])

  return { progress, events, connected, finished }
}
