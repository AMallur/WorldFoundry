import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const gatewayToken = 'a'.repeat(64);
const tables = {
  wf_gateway_config: [{ id: true, secret_hash: createHash('sha256').update(gatewayToken).digest('hex') }],
  wf_api_keys: [],
  wf_api_key_activity: [],
  wf_sessions: [],
  wf_projects: [
    { id: 'project-one', owner_id: 'user-one', name: 'One' },
    { id: 'project-two', owner_id: 'user-two', name: 'Two' },
  ],
};

class Query {
  constructor(table) { this.table = table; this.filters = []; this.fields = '*'; this.operation = 'select'; }
  select(fields = '*') { this.fields = fields; return this; }
  eq(field, value) { this.filters.push(row => row[field] === value); return this; }
  is(field, value) { this.filters.push(row => row[field] === value); return this; }
  in(field, values) { this.filters.push(row => values.includes(row[field])); return this; }
  order() { return this; }
  limit() { return this; }
  insert(value) { this.operation = 'insert'; this.value = value; return this; }
  update(value) { this.operation = 'update'; this.value = value; return this; }
  rows() {
    let rows;
    if (this.operation === 'insert') {
      const row = { id: `key-${this.table.length + 1}`, created_at: new Date().toISOString(),
        revoked_at: null, last_used_at: null, ...this.value };
      this.table.push(row);
      rows = [row];
    } else {
      rows = this.table.filter(row => this.filters.every(filter => filter(row)));
      if (this.operation === 'update') rows.forEach(row => Object.assign(row, this.value));
    }
    if (this.fields === '*') return rows;
    return rows.map(row => Object.fromEntries(this.fields.split(',').map(field => [field, row[field]])));
  }
  then(resolve) { return Promise.resolve({ data: this.rows(), error: null }).then(resolve); }
  maybeSingle() { return Promise.resolve({ data: this.rows()[0] ?? null, error: null }); }
  single() { return this.maybeSingle(); }
}

const client = {
  from(table) { return new Query(tables[table] ?? []); },
  async rpc(name, { p_key_id, p_owner_id, p_method, p_route }) {
    assert.equal(name, 'wf_record_api_key_use');
    const key = tables.wf_api_keys.find(row => row.id === p_key_id && row.owner_id === p_owner_id);
    if (!key || key.revoked_at) return { data: false, error: null };
    key.request_count = (key.request_count ?? 0) + 1;
    key.last_used_at = new Date().toISOString();
    tables.wf_api_key_activity.push({ key_id: key.id, owner_id: key.owner_id,
      method: p_method, route: p_route, created_at: new Date().toISOString() });
    return { data: true, error: null };
  },
  auth: {
    async getUser(token) { return token === 'signed-in-token'
      ? { data: { user: { id: 'user-one' } }, error: null }
      : { data: { user: null }, error: new Error('bad token') }; },
    async signInWithPassword({ email, password }) { return email === 'user@example.test' && password === 'password'
      ? { data: { user: { id: 'user-one' }, session: { access_token: 'provider-token' } }, error: null }
      : { data: { user: null }, error: new Error('bad password') }; },
  },
};

let serve;
const source = readFileSync(new URL('../supabase/functions/worldfoundry-customer-api/index.ts', import.meta.url), 'utf8')
  .replace(/^import .+\n/, '');
vm.runInNewContext(stripTypeScriptTypes(source), {
  createClient: () => client,
  Deno: { env: { get(name) { return ({ SUPABASE_URL: 'https://provider.test',
    SUPABASE_ANON_KEY: 'public-key', SUPABASE_SERVICE_ROLE_KEY: 'company-key' })[name]; } },
    serve(fn) { serve = fn; } },
  crypto: webcrypto, TextEncoder, URL, Date, Response, Request, Headers, Blob,
});

function request(path, { method = 'GET', headers = {}, body } = {}) {
  return serve(new Request(`https://provider.test/functions/v1/worldfoundry-customer-api/v1/${path}`, {
    method, headers: { 'x-wf-gateway-token': gatewayToken, ...headers },
    body: body ? JSON.stringify(body) : undefined,
  }));
}

test('WorldFoundry gateway, key issuance, tenant isolation, and revocation', async () => {
  const direct = await serve(new Request('https://provider.test/v1/health'));
  assert.equal(direct.status, 404);

  const login = await request('auth/login', { method: 'POST', body: {
    email: 'user@example.test', password: 'password',
  } });
  assert.equal(login.status, 200, await login.text());
  const cookies = login.headers.getSetCookie();
  const sessionCookie = cookies.find(value => value.startsWith('wf_session='));
  const csrfCookie = cookies.find(value => value.startsWith('wf_csrf='));
  assert.ok(sessionCookie.includes('HttpOnly'));
  assert.match(sessionCookie, /^wf_session=wf_sess_[0-9a-f]{64}/);
  assert.equal(sessionCookie.includes('provider-token'), false);
  assert.equal(JSON.stringify(tables.wf_sessions).includes('wf_sess_'), false);
  const csrf = csrfCookie.match(/^wf_csrf=([^;]+)/)[1];
  const headers = { cookie: `${sessionCookie.split(';')[0]}; ${csrfCookie.split(';')[0]}` };

  const noCsrf = await request('keys', { method: 'POST', headers, body: { name: 'Test' } });
  assert.equal(noCsrf.status, 401);
  const issued = await request('keys', { method: 'POST',
    headers: { ...headers, 'x-wf-csrf': csrf }, body: { name: 'Test' } });
  assert.equal(issued.status, 201);
  const key = await issued.json();
  assert.match(key.api_key, /^wf_live_[0-9a-f]{64}$/);
  assert.equal(tables.wf_api_keys[0].key_hash,
    createHash('sha256').update(key.api_key).digest('hex'));
  assert.equal(JSON.stringify(tables.wf_api_keys).includes(key.api_key), false);

  const auth = { authorization: `Bearer ${key.api_key}` };
  const own = await request('projects/project-one', { headers: auth });
  assert.equal(own.status, 200);
  const other = await request('projects/project-two', { headers: auth });
  assert.equal(other.status, 404);
  const detail = await request(`keys/${key.id}`, { headers });
  assert.equal((await detail.json()).request_count, 2);
  const activity = await request(`keys/${key.id}/activity`, { headers });
  const recorded = (await activity.json()).data;
  assert.equal(recorded.length, 2);
  assert.ok(recorded.some(item => item.route === '/v1/projects/project-two'));

  const scopedIssue = await request('keys', { method: 'POST',
    headers: { ...headers, 'x-wf-csrf': csrf },
    body: { name: 'Read only', scopes: ['read'], project_id: 'project-one' } });
  assert.equal(scopedIssue.status, 201);
  const scoped = await scopedIssue.json();
  const scopedAuth = { authorization: `Bearer ${scoped.api_key}` };
  assert.equal((await request('projects/project-one', { headers: scopedAuth })).status, 200);
  assert.equal((await request('projects/project-two', { headers: scopedAuth })).status, 404);
  assert.equal((await request('projects', { method: 'POST', headers: scopedAuth,
    body: { name: 'No write' } })).status, 403);

  const revoke = await request(`keys/${key.id}`, { method: 'DELETE',
    headers: { ...headers, 'x-wf-csrf': csrf } });
  assert.equal(revoke.status, 200);
  const after = await request('projects', { headers: auth });
  assert.equal(after.status, 401);

  const logout = await request('auth/logout', { method: 'POST', headers });
  assert.equal(logout.status, 200);
  assert.ok(tables.wf_sessions[0].revoked_at);
  const sessionAfterLogout = await request('keys', { headers });
  assert.equal(sessionAfterLogout.status, 401);
});
