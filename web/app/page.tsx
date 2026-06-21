"use client";

import { useRef, useState } from "react";
import { API_BASE, EventEnvelope, JobNode } from "@/lib/types";

// Minimal P0 shell: submit a goal, open the session SSE stream, and render the
// live agent tree (one card per job) + a log feed. Phase 4 fleshes this out with
// the recharts metric charts and a proper tree layout.
export default function Home() {
  const [goal, setGoal] = useState(
    "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Record<string, JobNode>>({});
  const [feed, setFeed] = useState<string[]>([]);
  const esRef = useRef<EventSource | null>(null);

  async function start() {
    esRef.current?.close();
    setJobs({});
    setFeed([]);
    const res = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal }),
    });
    const { session_id } = await res.json();
    setSessionId(session_id);

    const es = new EventSource(`${API_BASE}/sessions/${session_id}/stream`);
    esRef.current = es;
    const types = ["log", "metric", "status", "spawn", "artifact", "summary"];
    for (const t of types) {
      es.addEventListener(t, (e) =>
        apply(JSON.parse((e as MessageEvent).data) as EventEnvelope)
      );
    }
  }

  function apply(ev: EventEnvelope) {
    setJobs((prev) => {
      const j: JobNode = prev[ev.job_id] ?? {
        jobId: ev.job_id,
        parentJobId: ev.parent_job_id,
        depth: ev.depth,
        status: "pending",
        rewards: [],
        artifacts: [],
        logs: [],
      };
      const next = { ...j };
      const p = ev.payload || {};
      if (ev.type === "status") next.status = p.status ?? next.status;
      if (ev.type === "spawn") {
        next.kind = p.kind;
        next.goal = p.goal;
        next.status = "running";
      }
      const mReward =
        typeof p.reward === "number"
          ? p.reward
          : typeof p.metrics?.reward === "number"
          ? p.metrics.reward
          : undefined;
      const mStep = p.step ?? p.metrics?.step ?? 0;
      if (ev.type === "metric" && typeof mReward === "number") {
        next.rewards = [...next.rewards, { step: mStep, reward: mReward }];
        next.lastReward = mReward;
      }
      if (ev.type === "artifact" && p.url)
        next.artifacts = [...next.artifacts, { url: p.url, caption: p.caption }];
      if (ev.type === "summary") {
        next.summary = p.summary;
        next.status = "done";
      }
      if (ev.type === "log" && p.text)
        next.logs = [...next.logs, String(p.text)].slice(-5);
      return { ...prev, [ev.job_id]: next };
    });
    if (ev.type === "summary" || ev.type === "status") {
      setFeed((f) =>
        [
          ...f,
          `[${ev.type}] ${ev.job_id}: ${ev.payload?.summary ?? ev.payload?.status ?? ""}`,
        ].slice(-50)
      );
    }
  }

  const nodes = Object.values(jobs).sort((a, b) => a.depth - b.depth);

  return (
    <main className="grid">
      <section className="panel">
        <h2>AlphaResearch</h2>
        <p className="muted">Give the lead agent a research goal.</p>
        <input value={goal} onChange={(e) => setGoal(e.target.value)} />
        <button onClick={start}>Run</button>
        {sessionId && <p className="muted">session: {sessionId}</p>}
        <h3>Feed</h3>
        {feed.map((line, i) => (
          <div key={i} className="log">
            {line}
          </div>
        ))}
      </section>

      <section className="panel">
        <h3>Agent tree</h3>
        {nodes.length === 0 && <p className="muted">No jobs yet.</p>}
        {nodes.map((j) => (
          <div key={j.jobId} className="card" style={{ marginLeft: j.depth * 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>{j.goal ?? j.jobId}</strong>
              <span className={`badge ${j.status}`}>{j.status}</span>
            </div>
            {j.lastReward !== undefined && (
              <div className="muted">reward: {j.lastReward.toFixed(3)}</div>
            )}
            {j.summary && <div>{j.summary}</div>}
            {j.artifacts.map((a, i) => (
              <img
                key={i}
                className="artifact"
                src={a.url.startsWith("http") ? a.url : `${API_BASE}${a.url}`}
                alt={a.caption ?? ""}
              />
            ))}
            {j.logs.map((l, i) => (
              <div key={i} className="log">
                {l}
              </div>
            ))}
          </div>
        ))}
      </section>
    </main>
  );
}
