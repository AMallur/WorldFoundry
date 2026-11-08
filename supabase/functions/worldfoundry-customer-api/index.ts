import { createClient } from 'npm:@supabase/supabase-js@2.95.0'

// This function is company infrastructure. Customers reach it through a
// WorldFoundry-owned gateway, never through the provider URL directly.
const providerUrl = Deno.env.get('SUPABASE_URL') ?? ''
const publicKey = Deno.env.get('SUPABASE_ANON_KEY') ?? ''
const companyKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
const admin = providerUrl && companyKey
  ? createClient(providerUrl, companyKey, { auth: { persistSession: false } }) : null
const identity = () => createClient(providerUrl, publicKey,
  { auth: { persistSession: false, autoRefreshToken: false } })

const reply = (data: unknown, status = 200, headers: HeadersInit = {}) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store', ...headers } })
const error = (message: string, status = 400) => reply({ error: message }, status)
const cookie = (req: Request, name: string) => req.headers.get('cookie')
  ?.split(';').map(part => part.trim()).find(part => part.startsWith(`${name}=`))
  ?.slice(name.length + 1)

async function digest(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('')
}

function randomHex(bytes = 32): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)),
    byte => byte.toString(16).padStart(2, '0')).join('')
}

type Caller = { ownerId: string, scopes: string[], boundProject: string | null, session: boolean }

async function authenticate(req: Request): Promise<Caller | null> {
  const bearer = req.headers.get('authorization')?.match(/^Bearer (.+)$/i)?.[1]
  if (bearer?.startsWith('wf_live_')) {
    if (!/^wf_live_[0-9a-f]{64}$/.test(bearer)) return null
    const keyHash = await digest(bearer)
    const { data } = await admin!.from('wf_api_keys')
      .select('id,owner_id,project_id,scopes,expires_at,revoked_at')
      .eq('key_hash', keyHash).maybeSingle()
    if (!data || data.revoked_at || (data.expires_at && Date.parse(data.expires_at) <= Date.now())) return null
    return { ownerId: data.owner_id, scopes: data.scopes, boundProject: data.project_id, session: false }
  }
  const sessionToken = cookie(req, 'wf_session')
  if (!sessionToken || !/^wf_sess_[0-9a-f]{64}$/.test(sessionToken)) return null
  const { data: session } = await admin!.from('wf_sessions')
    .select('owner_id,expires_at,revoked_at')
    .eq('token_hash', await digest(sessionToken)).maybeSingle()
  if (!session || session.revoked_at || Date.parse(session.expires_at) <= Date.now()) return null
  const csrf = cookie(req, 'wf_csrf')
  if (!['GET', 'HEAD'].includes(req.method) &&
      (!csrf || req.headers.get('x-wf-csrf') !== csrf)) return null
  return { ownerId: session.owner_id, scopes: ['read', 'write'], boundProject: null, session: true }
}

function permitted(caller: Caller, projectId: string): boolean {
  return !caller.boundProject || caller.boundProject === projectId
}

async function ownedProject(caller: Caller, projectId: string): Promise<boolean> {
  if (!permitted(caller, projectId)) return false
  const { data } = await admin!.from('wf_projects').select('id').eq('id', projectId)
    .eq('owner_id', caller.ownerId).maybeSingle()
  return !!data
}

async function ownedRun(caller: Caller, runId: string) {
  const { data } = await admin!.from('wf_runs').select('*').eq('id', runId).maybeSingle()
  if (!data || !(await ownedProject(caller, data.project_id))) return null
  return data
}

async function ownedEpisode(caller: Caller, episodeId: string) {
  const { data } = await admin!.from('wf_episodes').select('*').eq('id', episodeId).maybeSingle()
  if (!data || !(await ownedRun(caller, data.run_id))) return null
  return data
}

const kinds: Record<string, string> = {
  environments: 'environment', agents: 'agent', scenarios: 'scenario',
  datasets: 'dataset', policies: 'policy', validators: 'validator',
}
const safeEpisode = (episode: Record<string, unknown>) => {
  const { trace_object_key: _internal, ...customerFields } = episode
  return customerFields
}

Deno.serve(async (req: Request) => {
  if (!admin || !publicKey) return error('WorldFoundry service unavailable', 503)
  const gatewayToken = req.headers.get('x-wf-gateway-token')
  if (!gatewayToken || !/^[0-9a-f]{64}$/.test(gatewayToken)) return error('Not found', 404)
  const { data: gateway } = await admin.from('wf_gateway_config').select('secret_hash')
    .eq('id', true).maybeSingle()
  if (!gateway || await digest(gatewayToken) !== gateway.secret_hash)
    return error('Not found', 404)
  const parts = new URL(req.url).pathname.split('/').filter(Boolean)
  const v1 = parts.lastIndexOf('v1')
  if (v1 < 0) return error('Not found', 404)
  const collection = parts[v1 + 1]
  const id = parts[v1 + 2]
  const subresource = parts[v1 + 3]

  if (collection === 'health' && req.method === 'GET') return reply({ status: 'ok' })
  let body: Record<string, any> = {}
  if (['POST', 'PATCH'].includes(req.method) && !(collection === 'auth' && id === 'logout')) {
    try {
      body = await req.json()
      if (!body || Array.isArray(body) || typeof body !== 'object') return error('JSON object required')
    } catch { return error('Invalid JSON') }
  }

  // Supabase Auth is called only inside company infrastructure. The browser
  // receives an opaque WorldFoundry session, never the provider's JWT.
  if (collection === 'auth' && id === 'signup' && req.method === 'POST') {
    if (typeof body.email !== 'string' || typeof body.password !== 'string') return error('Email and password required')
    const { error: signupError } = await identity().auth.signUp({ email: body.email, password: body.password })
    return signupError ? error('Could not create account', 400) : reply({ status: 'verification_required' }, 201)
  }
  if (collection === 'auth' && id === 'login' && req.method === 'POST') {
    if (typeof body.email !== 'string' || typeof body.password !== 'string') return error('Email and password required')
    const { data, error: loginError } = await identity().auth.signInWithPassword({ email: body.email, password: body.password })
    if (loginError || !data.user) return error('Invalid credentials', 401)
    const sessionToken = `wf_sess_${randomHex()}`
    const lifetime = 7 * 24 * 60 * 60
    const { error: sessionError } = await admin.from('wf_sessions').insert({
      owner_id: data.user.id, token_hash: await digest(sessionToken),
      expires_at: new Date(Date.now() + lifetime * 1000).toISOString(),
    })
    if (sessionError) return error('Could not start session', 500)
    const csrf = randomHex(24)
    const headers = new Headers({ 'Cache-Control': 'no-store', 'Content-Type': 'application/json' })
    headers.append('Set-Cookie', `wf_session=${sessionToken}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${lifetime}`)
    headers.append('Set-Cookie', `wf_csrf=${csrf}; Secure; SameSite=Strict; Path=/; Max-Age=${lifetime}`)
    return new Response(JSON.stringify({ status: 'signed_in', expires_in: lifetime }), { headers })
  }
  if (collection === 'auth' && id === 'logout' && req.method === 'POST') {
    const sessionToken = cookie(req, 'wf_session')
    if (sessionToken && /^wf_sess_[0-9a-f]{64}$/.test(sessionToken)) {
      await admin.from('wf_sessions').update({ revoked_at: new Date().toISOString() })
        .eq('token_hash', await digest(sessionToken)).is('revoked_at', null)
    }
    const headers = new Headers({ 'Cache-Control': 'no-store', 'Content-Type': 'application/json' })
    headers.append('Set-Cookie', 'wf_session=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0')
    headers.append('Set-Cookie', 'wf_csrf=; Secure; SameSite=Strict; Path=/; Max-Age=0')
    return new Response(JSON.stringify({ status: 'signed_out' }), { headers })
  }

  const caller = await authenticate(req)
  if (!caller) return error('Unauthorized', 401)
  if (collection === 'auth' && id === 'me' && req.method === 'GET')
    return reply({ account_id: caller.ownerId })

  if (collection === 'keys') {
    if (!caller.session) return error('Dashboard session required', 403)
    if (req.method === 'GET' && !id) {
      const { data, error: dbError } = await admin.from('wf_api_keys')
        .select('id,name,key_prefix,project_id,scopes,created_at,expires_at,revoked_at,last_used_at')
        .eq('owner_id', caller.ownerId).order('created_at', { ascending: false })
      return dbError ? error('Could not list keys', 500) : reply({ data })
    }
    if (req.method === 'POST' && !id) {
      if (typeof body.name !== 'string' || !body.name.trim() || body.name.length > 100)
        return error('name is required (1..100 characters)')
      const scopes = body.scopes ?? ['read', 'write']
      if (!Array.isArray(scopes) || !scopes.length || scopes.some(s => !['read', 'write'].includes(s)))
        return error('Invalid scopes')
      if (body.project_id != null &&
          (typeof body.project_id !== 'string' || !(await ownedProject(caller, body.project_id))))
        return error('Unknown project', 404)
      if (body.expires_at != null &&
          (typeof body.expires_at !== 'string' || !Number.isFinite(Date.parse(body.expires_at)) ||
           Date.parse(body.expires_at) <= Date.now())) return error('Invalid expiry')
      const token = `wf_live_${randomHex()}`
      const { data, error: dbError } = await admin.from('wf_api_keys').insert({
        owner_id: caller.ownerId, project_id: body.project_id ?? null,
        name: body.name.trim(), key_prefix: token.slice(0, 18),
        key_hash: await digest(token), scopes, expires_at: body.expires_at ?? null,
      }).select('id,name,key_prefix,project_id,scopes,created_at,expires_at').single()
      if (dbError) return error('Could not create key', 500)
      return reply({ ...data, api_key: token }, 201)
    }
    if (req.method === 'DELETE' && id) {
      const { data, error: dbError } = await admin.from('wf_api_keys')
        .update({ revoked_at: new Date().toISOString() }).eq('id', id)
        .eq('owner_id', caller.ownerId).is('revoked_at', null)
        .select('id,revoked_at').maybeSingle()
      return dbError ? error('Could not revoke key', 500) : data ? reply(data) : error('Key not found', 404)
    }
    return error('Not found', 404)
  }

  const scope = req.method === 'GET' ? 'read' : 'write'
  if (!caller.scopes.includes(scope)) return error('Insufficient key scope', 403)

  if (collection === 'projects') {
    if (req.method === 'POST' && !id) {
      if (typeof body.name !== 'string' || !body.name.trim()) return error('name is required')
      if (caller.boundProject) return error('Project-scoped key cannot create projects', 403)
      const { data, error: dbError } = await admin.from('wf_projects')
        .insert({ owner_id: caller.ownerId, name: body.name.trim() }).select().single()
      return dbError ? error('Could not create project', 500) : reply(data, 201)
    }
    if (req.method === 'GET') {
      let query = admin.from('wf_projects').select('*').eq('owner_id', caller.ownerId)
      if (id) query = query.eq('id', id)
      if (caller.boundProject) query = query.eq('id', caller.boundProject)
      const { data, error: dbError } = await query
      return dbError ? error('Could not read projects', 500) : id ?
        data?.[0] ? reply(data[0]) : error('Project not found', 404) : reply({ data })
    }
  }

  const kind = kinds[collection]
  if (kind) {
    if (req.method === 'POST' && !id) {
      if (typeof body.project_id !== 'string' || !(await ownedProject(caller, body.project_id)))
        return error('Unknown project', 404)
      if (typeof body.name !== 'string' || !body.name.trim()) return error('name is required')
      const { project_id, name, version = 1, ...config } = body
      if (!Number.isInteger(version) || version < 1) return error('Invalid version')
      const { data, error: dbError } = await admin.from('wf_resources').insert({
        project_id, kind, name: name.trim(), version, config,
      }).select().single()
      return dbError ? error('Could not create resource', 500) : reply(data, 201)
    }
    if (req.method === 'GET') {
      const { data: projects } = await admin.from('wf_projects').select('id')
        .eq('owner_id', caller.ownerId)
      const ids = (projects ?? []).map(project => project.id)
        .filter(projectId => permitted(caller, projectId))
      if (!ids.length) return id ? error('Resource not found', 404) : reply({ data: [] })
      let query = admin.from('wf_resources').select('*').eq('kind', kind).in('project_id', ids)
      if (id) query = query.eq('id', id)
      const { data, error: dbError } = await query
      return dbError ? error('Could not read resources', 500) : id ?
        data?.[0] ? reply(data[0]) : error('Resource not found', 404) : reply({ data })
    }
  }

  if (collection === 'training-runs') {
    if (req.method === 'POST' && !id) {
      const { project_id, agent_id, environment_id, episodes = 1, ...config } = body
      if (typeof project_id !== 'string' || !(await ownedProject(caller, project_id)))
        return error('Unknown project', 404)
      if (![agent_id, environment_id].every(value => typeof value === 'string'))
        return error('agent_id and environment_id required')
      if (!Number.isInteger(episodes) || episodes < 1 || episodes > 10000)
        return error('episodes must be 1..10000')
      const { data: resources } = await admin.from('wf_resources')
        .select('id,kind,project_id').in('id', [agent_id, environment_id])
        .eq('project_id', project_id)
      if (!resources?.some(resource => resource.id === agent_id && resource.kind === 'agent') ||
          !resources?.some(resource => resource.id === environment_id && resource.kind === 'environment'))
        return error('Agent and environment must belong to this project', 400)
      const { data, error: dbError } = await admin.from('wf_runs').insert({
        project_id, agent_id, environment_id, requested_episodes: episodes,
        config, status: 'queued',
      }).select().single()
      return dbError ? error('Could not create run', 500) : reply(data, 201)
    }
    if (req.method === 'GET') {
      if (id) {
        const run = await ownedRun(caller, id)
        return run ? reply(run) : error('Run not found', 404)
      }
      const { data: projects } = await admin.from('wf_projects').select('id').eq('owner_id', caller.ownerId)
      const ids = (projects ?? []).map(project => project.id).filter(projectId => permitted(caller, projectId))
      if (!ids.length) return reply({ data: [] })
      const { data, error: dbError } = await admin.from('wf_runs').select('*')
        .in('project_id', ids).order('created_at', { ascending: false })
      return dbError ? error('Could not list runs', 500) : reply({ data })
    }
    if (req.method === 'PATCH' && id) {
      const run = await ownedRun(caller, id)
      if (!run) return error('Run not found', 404)
      if (!['running', 'completed', 'failed', 'cancelled'].includes(body.status))
        return error('Invalid status')
      const { data, error: dbError } = await admin.from('wf_runs').update({
        status: body.status,
        finished_at: body.status === 'running' ? null : new Date().toISOString(),
      }).eq('id', id).eq('project_id', run.project_id).select().single()
      return dbError ? error('Could not update run', 500) : reply(data)
    }
  }

  if (collection === 'episodes') {
    if (req.method === 'POST' && !id) {
      const { run_id, ordinal, seed, status, score, error_code } = body
      const run = typeof run_id === 'string' ? await ownedRun(caller, run_id) : null
      if (!run) return error('Run not found', 404)
      if (!Number.isInteger(ordinal) || ordinal < 0 || ordinal >= run.requested_episodes ||
          !Number.isInteger(seed)) return error('Invalid ordinal or seed')
      if (!['passed', 'failed', 'service_error'].includes(status)) return error('Invalid status')
      if (typeof score !== 'number' || score < 0 || score > 1) return error('Invalid score')
      const { data, error: dbError } = await admin.from('wf_episodes').insert({
        run_id, ordinal, seed, status, score, error_code: error_code ?? null,
      }).select().single()
      if (dbError) return error('Could not create episode', 500)
      // Client reports are operational only; never use this ledger for billing.
      await admin.from('wf_usage').insert({ project_id: run.project_id,
        run_id, episode_id: data.id, unit: 'episode', quantity: 1, source: 'client_reported' })
      return reply(safeEpisode(data), 201)
    }
    if (id && subresource === 'trace' && req.method === 'POST') {
      const episode = await ownedEpisode(caller, id)
      if (!episode) return error('Episode not found', 404)
      if (episode.trace_object_key) return error('Trace already exists', 409)
      if (!Array.isArray(body.events) || body.events.length > 10000 ||
          body.events.some(event => !event || typeof event !== 'object'))
        return error('events array required (max 10000)')
      const objectKey = `${caller.ownerId}/${episode.run_id}/${id}.jsonl`
      const payload = body.events.map(event => JSON.stringify(event)).join('\n') + '\n'
      if (payload.length > 5_000_000) return error('Trace too large', 413)
      const { error: uploadError } = await admin.storage.from('wf-traces').upload(objectKey,
        new Blob([payload], { type: 'application/x-ndjson' }), { upsert: false })
      if (uploadError) return error('Could not save trace', 500)
      const { error: updateError } = await admin.from('wf_episodes')
        .update({ trace_object_key: objectKey }).eq('id', id)
      return updateError ? error('Could not attach trace', 500) : reply({ episode_id: id }, 201)
    }
    if (id && subresource === 'trace' && req.method === 'GET') {
      const episode = await ownedEpisode(caller, id)
      if (!episode?.trace_object_key) return error('Trace not found', 404)
      const { data, error: downloadError } = await admin.storage.from('wf-traces')
        .download(episode.trace_object_key)
      return downloadError ? error('Could not read trace', 500) :
        new Response(data, { headers: { 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-store' } })
    }
    if (req.method === 'GET') {
      if (id) {
        const episode = await ownedEpisode(caller, id)
        return episode ? reply(safeEpisode(episode)) : error('Episode not found', 404)
      }
      const runId = new URL(req.url).searchParams.get('run_id')
      if (!runId) return error('run_id query parameter required')
      if (!(await ownedRun(caller, runId))) return error('Run not found', 404)
      const { data, error: dbError } = await admin.from('wf_episodes').select('*')
        .eq('run_id', runId).order('ordinal')
      return dbError ? error('Could not list episodes', 500) : reply({ data: data.map(safeEpisode) })
    }
  }
  return error('Not found', 404)
})
