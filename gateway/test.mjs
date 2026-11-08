import assert from 'node:assert/strict';
import { test } from 'node:test';
import handler from './api/proxy.js';

const oldFetch = globalThis.fetch;
const oldUrl = process.env.WF_INTERNAL_API_URL;
const oldToken = process.env.WF_GATEWAY_TOKEN;

function response() {
  return {
    headers: {}, statusCode: 200, body: null,
    setHeader(name, value) { this.headers[name] = value; },
    status(code) { this.statusCode = code; return this; },
    json(value) { this.body = value; return this; },
    send(value) { this.body = value; return this; },
  };
}

test('gateway hides provider address and injects server credential', async () => {
  process.env.WF_INTERNAL_API_URL = 'https://provider.example/functions/v1/worldfoundry-customer-api';
  process.env.WF_GATEWAY_TOKEN = 'secret-on-server';
  let called;
  globalThis.fetch = async (url, options) => {
    called = { url: String(url), options };
    return new Response(JSON.stringify({ data: [] }), {
      headers: { 'content-type': 'application/json',
        'set-cookie': '__cf_bm=provider-cookie; Domain=supabase.co' },
    });
  };
  const res = response();
  await handler({
    method: 'GET', query: { route: 'projects' }, url: '/api/proxy?route=projects',
    headers: { authorization: 'Bearer wf_live_example', 'x-wf-gateway-token': 'attacker' },
  }, res);
  assert.equal(res.statusCode, 200);
  assert.equal(called.url, 'https://provider.example/functions/v1/worldfoundry-customer-api/v1/projects');
  assert.equal(called.options.headers['x-wf-gateway-token'], 'secret-on-server');
  assert.equal(called.options.headers.authorization, 'Bearer wf_live_example');
  assert.equal(res.headers['Cache-Control'], 'no-store');
  assert.equal(res.headers['Set-Cookie'], undefined);
  assert.equal(String(res.body).includes('provider.example'), false);
});

test('gateway rejects malformed routes before calling provider', async () => {
  globalThis.fetch = () => { throw new Error('should not fetch'); };
  const res = response();
  await handler({ method: 'GET', query: { route: '../secrets' }, url: '/api/proxy', headers: {} }, res);
  assert.equal(res.statusCode, 404);
});

test.after(() => {
  globalThis.fetch = oldFetch;
  if (oldUrl === undefined) delete process.env.WF_INTERNAL_API_URL;
  else process.env.WF_INTERNAL_API_URL = oldUrl;
  if (oldToken === undefined) delete process.env.WF_GATEWAY_TOKEN;
  else process.env.WF_GATEWAY_TOKEN = oldToken;
});
