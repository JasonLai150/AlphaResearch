# Redis keyspace (plan §4)

Redis Stack: RedisJSON for entity docs, Streams for the event bus + session queue,
plain integers for the atomic budget.

## Entities (RedisJSON)
| Key | Shape |
|---|---|
| `session:{sid}` | `{ id, user_id, goal, status, created_at }` |
| `session:{sid}:budget` | INT — atomic; `DECRBY` on dispatch, refuse if result `< 0` |
| `job:{jid}` | `{ id, session_id, parent_job_id\|null, depth, kind, status, params, gpu, modal_call_id, created_at }` |
| `run:{jid}` | `{ job_id, status, summary, metrics, created_at }` — final result, flows UP |
| `artifact:{aid}` | `{ id, job_id, kind, url, caption, bytes }` — blob lives in GCS |

`kind ∈ {agent, experiment}` · `status ∈ {pending, running, done, failed}`

## Relationships (Sets)
| Key | Members |
|---|---|
| `session:{sid}:jobs` | all job ids in the session |
| `job:{jid}:children` | child job ids — the tree (edges = parent_job_id) |

## Streams
| Key | Fields | Notes |
|---|---|---|
| `session:{sid}:events` | `{ data: <EventEnvelope json> }` | every job at every depth `XADD`s; SSE = `XREAD BLOCK`. Entry id is the SSE `Last-Event-ID`. |
| `sessions:queue` | `{ session_id }` | depth-0 work; worker `XREADGROUP` |

`EventEnvelope.type ∈ {log, metric, status, spawn, artifact, summary}`

## Notes
- Budget is the seed of compute-allocation v0: one atomic `DECRBY` per dispatch.
- Stream entry ids are monotonic → replay/reconnect is just `XREAD` from `Last-Event-ID`.
- `parent_job_id` + `depth` + `session_id` are all the structure recursion needs.
