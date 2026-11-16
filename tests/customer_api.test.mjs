import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import { validateEnvironment, validateScenario, applyAction, grade } from
  '../supabase/functions/worldfoundry-customer-api/runtime.ts';

const gatewayToken = 'a'.repeat(64);
const tables = {
  wf_gateway_config: [{ id: true, secret_hash: createHash('sha256').update(gatewayToken).digest('hex') }],
  wf_api_keys: [],
  wf_api_key_activity: [],
  wf_sim_sessions: [],
  wf_sim_events: [],
  wf_resources: [
    { id: 'env-one', project_id: 'project-one', kind: 'environment',
      config: { initial_state: { tickets: { T1: { status: 'open' } } },
        actions: { resolve: { operation: 'set', path: 'tickets.$ticket_id.status',
          value: 'closed', parameters: { ticket_id: { type: 'string' } } } } } },
    { id: 'scenario-one', project_id: 'project-one', kind: 'scenario',
      config: { checks: [{ name: 'resolved', path: 'tickets.T1.status', equals: 'closed' }] } },
  ],
  wf_sessions: [],
  wf_projects: [
    { id: 'project-one', owner_id: 'user-one', name: 'One' },
    { id: 'project-two', owner_id: 'user-two', name: 'Two' },
  ],
};

class Query {
  constructor(table, name) { this.table = table; this.name = name; this.filters = []; this.fields = '*'; this.operation = 'select'; }
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
      if (this.name === 'wf_sim_sessions') {
        Object.assign(row, { status: 'running', version: 0, step: 0, score: null });
      }
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
  from(table) { return new Query(tables[table] ?? [], table); },
  async rpc(name, { p_key_id, p_owner_id, p_method, p_route }) {
    if (name === 'wf_sim_commit') {
      const args = arguments[1];
      const session = tables.wf_sim_sessions.find(row => row.id === args.p_session_id);
      if (!session) return { data: { error: 'not_found' }, error: null };
      if (session.version !== args.p_expected_version)
        return { data: { error: 'conflict' }, error: null };
      session.version += 1;
      if (args.p_action !== '__submit__') session.step += 1;
      session.state = args.p_next_state;
      session.status = args.p_status;
      session.score = args.p_score;
      session.checks = args.p_checks;
      tables.wf_sim_events.push({ session_id: session.id, project_id: session.project_id,
        version: session.version, call_id: args.p_call_id, action: args.p_action,
        parameters: args.p_parameters, observation: args.p_observation });
      return { data: { session }, error: null };
    }
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
  .replace(/^import .+\n/gm, '');
vm.runInNewContext(stripTypeScriptTypes(source), {
  createClient: () => client,
  Deno: { env: { get(name) { return ({ SUPABASE_URL: 'https://provider.test',
    SUPABASE_ANON_KEY: 'public-key', SUPABASE_SERVICE_ROLE_KEY: 'company-key' })[name]; } },
    serve(fn) { serve = fn; } },
  crypto: webcrypto, TextEncoder, URL, Date, Response, Request, Headers, Blob,
  validateEnvironment, validateScenario, applyAction, grade,
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

test('hosted simulation API persists state and blocks cross-tenant access', async () => {
  const token = 'wf_live_' + 'b'.repeat(64);
  tables.wf_api_keys.push({
    id: 'sim-key', owner_id: 'user-one', project_id: 'project-one',
    key_hash: createHash('sha256').update(token).digest('hex'),
    scopes: ['read', 'write'], revoked_at: null, expires_at: null,
  });
  const auth = { authorization: 'Bearer ' + token };
  const started = await request('simulation-sessions', {
    method: 'POST', headers: auth,
    body: { project_id: 'project-one', environment_id: 'env-one',
      scenario_id: 'scenario-one', max_steps: 10 },
  });
  assert.equal(started.status, 201, await started.clone().text());
  const session = await started.json();
  assert.equal(session.status, 'running');
  assert.equal(session.version, 0);
  const action = await request('simulation-sessions/' + session.id + '/actions', {
    method: 'POST', headers: auth,
    body: { action: 'resolve', expected_version: 0, call_id: 'resolve-001',
      parameters: { ticket_id: 'T1' } },
  });
  assert.equal(action.status, 200, await action.clone().text());
  const after = await action.json();
  assert.equal(after.state.tickets.T1.status, 'closed');
  const conflicting = await request('simulation-sessions/' + session.id + '/actions', {
    method: 'POST', headers: auth,
    body: { action: 'resolve', expected_version: 0, call_id: 'resolve-002',
      parameters: { ticket_id: 'T1' } },
  });
  assert.equal(conflicting.status, 409);
  const submitted = await request('simulation-sessions/' + session.id + '/submit', {
    method: 'POST', headers: auth,
    body: { expected_version: 1, call_id: 'submit-001' },
  });
  assert.equal(submitted.status, 200, await submitted.clone().text());
  const finalState = await submitted.json();
  assert.equal(finalState.status, 'passed');
  assert.equal(finalState.score, 1);
  const history = await request('simulation-sessions/' + session.id + '/events', { headers: auth });
  assert.equal(history.status, 200);
  assert.equal((await history.json()).data.length, 2);
  const other = await request('simulation-sessions', {
    method: 'POST', headers: auth,
    body: { project_id: 'project-two', environment_id: 'env-one',
      scenario_id: 'scenario-one' },
  });
  assert.equal(other.status, 404);
});
