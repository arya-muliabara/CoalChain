import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refresh } from './refresh.mjs';
test('worker sends authenticated request and returns snapshot', async () => {
  const result = await refresh('http://api:8000', 'test-secret', async (url, options) => {
    assert.equal(url.pathname, '/api/internal/refresh-alerts');
    assert.equal(options.headers.Authorization, 'Bearer test-secret');
    return {ok:true, json:async()=>({count:2})};
  });
  assert.equal(result.count, 2);
});
test('worker surfaces API failure', async () => {
  await assert.rejects(() => refresh('http://api', 'secret', async()=>({ok:false,status:401})), /401/);
});

