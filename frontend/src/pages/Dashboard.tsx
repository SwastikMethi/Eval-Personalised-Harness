import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { color, radius, space } from '../design/tokens'
import { rise, respectMotion, stagger } from '../design/motion'
import { font, measure, type } from '../design/typography'
import { Empty, Notice, Panel, Status } from '../ui'

export default function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1 })
  const experiments = useQuery({ queryKey: ['experiments'], queryFn: api.experiments })
  const repositories = useQuery({ queryKey: ['repositories'], queryFn: api.repositories })

  return (
    <div>
      <motion.header
        variants={respectMotion(rise)}
        initial="hidden"
        animate="shown"
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: space[5],
          flexWrap: 'wrap',
          marginBottom: space[6],
        }}
      >
        <div>
          <h1 style={{ ...type.title, fontWeight: 400, marginBottom: space[3] }}>
            Which stack is best for your repo?
          </h1>
          <p style={{ ...type.body, color: color.dim, maxWidth: measure }}>
            Benchmark coding-agent harnesses against open-weight models on tasks from your own
            repository, and get quality, reliability and efficiency recommendations.
          </p>
        </div>
        <Link
          to="/new"
          className="aso-focusable"
          style={{
            fontFamily: font.sans,
            fontSize: 13,
            fontWeight: 600,
            padding: '10px 20px',
            borderRadius: radius.md,
            background: color.live,
            color: color.onLive,
            whiteSpace: 'nowrap',
          }}
        >
          New run
        </Link>
      </motion.header>

      {health.isError && (
        <Notice tone="warn">
          Backend unreachable — run <code>make backend</code>.
        </Notice>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: space[4],
          alignItems: 'start',
        }}
      >
        <Panel label="Recent experiments">
          {experiments.data?.length ? (
            <motion.div variants={respectMotion(stagger())} initial="hidden" animate="shown">
              {experiments.data
                .slice()
                .reverse()
                .map((e) => (
                  <motion.div key={e.id} variants={respectMotion(rise)}>
                    <Link
                      to={`/experiments/${e.id}`}
                      className="aso-focusable"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: space[4],
                        padding: `${space[3]}px ${space[2]}px`,
                        margin: `0 -${space[2]}px`,
                        borderBottom: `1px solid ${color.lineSoft}`,
                        borderRadius: radius.sm,
                      }}
                    >
                      <span style={{ fontFamily: font.mono, fontSize: 13, color: color.text }}>
                        {e.name}
                      </span>
                      <Status
                        tone={e.status === 'running' ? 'live' : 'idle'}
                        pulse={e.status === 'running'}
                      >
                        {e.status}
                      </Status>
                    </Link>
                  </motion.div>
                ))}
            </motion.div>
          ) : (
            <Empty>No experiments yet — start one with “New run”.</Empty>
          )}
        </Panel>

        <Panel label="Repositories">
          {repositories.data?.length ? (
            <motion.div variants={respectMotion(stagger())} initial="hidden" animate="shown">
              {repositories.data.map((r) => (
                <motion.div
                  key={r.id}
                  variants={respectMotion(rise)}
                  style={{
                    padding: `${space[3]}px 0`,
                    borderBottom: `1px solid ${color.lineSoft}`,
                  }}
                >
                  <div style={{ fontFamily: font.mono, fontSize: 13, color: color.text }}>
                    {r.name}
                  </div>
                  <div
                    style={{
                      ...type.caption,
                      color: color.faint,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.source} · {r.path_or_url}
                  </div>
                </motion.div>
              ))}
            </motion.div>
          ) : (
            <Empty>No repositories registered.</Empty>
          )}
        </Panel>
      </div>
    </div>
  )
}
