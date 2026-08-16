import { useParams } from 'react-router-dom'
import RunPanel from './RunPanel'

/**
 * Standalone route for one run.
 *
 * Live now shows run detail inline, so this is only the deep-link entry point —
 * the body lives in RunPanel and is shared by both. Keeping the route means an
 * old bookmark or a link pasted into an issue still resolves.
 */
export default function RunDetail() {
  const { id } = useParams<{ id: string }>()
  if (!id) return null
  return <RunPanel runId={id} />
}
