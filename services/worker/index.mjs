import { setTimeout as delay } from 'node:timers/promises';
import { refresh } from './refresh.mjs';
const base = process.env.API_URL || 'http://127.0.0.1:8000';
const secret = process.env.MCMS_WORKER_SECRET;
if (!secret) throw new Error('MCMS_WORKER_SECRET is required');
const shutdown = new AbortController();
process.once('SIGTERM', () => shutdown.abort());
process.once('SIGINT', () => shutdown.abort());
while (!shutdown.signal.aborted) {
  try { const result = await refresh(base, secret); console.log(JSON.stringify({ event: 'alerts_refreshed', ...result })); }
  catch (error) { console.error(JSON.stringify({ event: 'refresh_failed', message: error.message })); }
  try { await delay(60000, undefined, {signal:shutdown.signal}); }
  catch (error) { if (error.name !== 'AbortError') throw error; }
}

