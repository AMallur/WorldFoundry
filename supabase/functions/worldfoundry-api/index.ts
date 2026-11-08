import { createClient } from 'npm:@supabase/supabase-js@2.95.0'

const url = Deno.env.get('SUPABASE_URL') ?? ''
const key = Deno.env.get('SUPABASE_ANON_KEY') ?? ''
const json = (value: unknown, status = 200) => Response.json(value, { status })
const fail = (message: string, status = 400) => json({ error: message }, status)

const allowedKinds = new Set(['environment', 'agent', 'scenario', 'dataset', 'policy', 'validator'])
const pathKinds: Record<string, string> = {
  environments: 'environment', agents: 'agent', scenarios: 'scenario',
  datasets: 'dataset', policies: 'policy', validators: 'validator',
}

Deno.serve(async (req: Request) => {
  const token = req.headers.get('authorization')?.match(/^Bearer (.+)$/i)?.[1]
  if (!token) return fail('Missing Supabase user access token', 401)
  if (!url || !key) return fail('Supabase function is not configured', 503)
  const db = createClient(url, key, { global: { headers: { Authorization: `Bearer ${token}` } } })
  const { data: auth, error: authError } = await db.auth.getUser(token)
  if (authError || !auth.user) return fail('Invalid user access token', 401)

  const parts = new URL(req.url).pathname.split('/').filter(Boolean)
  const v1 = parts.indexOf('v1')
  if (v1 < 0) return fail('Unknown route', 404)
  const collection = parts[v1 + 1]
  const id = parts[v1 + 2]
  const subresource = parts[v1 + 3]
  let body: Record<string, unknown> = {}
  if (req.method === 'POST' || req.method === 'PATCH') {
    try {
      body = await req.json()
      if (!body || Array.isArray(body) || typeof body !== 'object') return fail('JSON object required')
    } catch { return fail('Invalid JSON') }
  }

  try {
    if (collection === 'projects') {
      if (req.method === 'POST' && !id) {
        if (typeof body.name !== 'string' || !body.name.trim()) return fail('name is required')
        const { data, error } = await db.from('wf_projects').insert({ owner_id: auth.user.id, name: body.name }).select().single()
        return error ? fail(error.message) : json(data, 201)
      }
      if (req.method === 'GET') {
        const query = db.from('wf_projects').select('*')
        const { data, error } = await (id ? query.eq('id', id).single() : query.order('created_at', { ascending: false }))
        return error ? fail(error.message, 404) : json(id ? data : { data })
      }
    }

    const kind = pathKinds[collection]
    if (kind && allowedKinds.has(kind)) {
      if (req.method === 'POST' && !id) {
        const { project_id, name, version = 1, ...config } = body
        if (typeof project_id !== 'string' || typeof name !== 'string') return fail('project_id and name are required')
        const { data, error } = await db.from('wf_resources').insert({ project_id, kind, name, version, config }).select().single()
        return error ? fail(error.message) : json(data, 201)
      }
      if (req.method === 'GET') {
        let query = db.from('wf_resources').select('*').eq('kind', kind)
        if (id) query = query.eq('id', id)
        const { data, error } = await query
        return error ? fail(error.message) : json(id ? data?.[0] ?? null : { data })
      }
    }

    if (collection === 'training-runs') {
      if (req.method === 'POST' && !id) {
        const { project_id, agent_id, environment_id, episodes = 1, ...config } = body
        if (![project_id, agent_id, environment_id].every(v => typeof v === 'string')) return fail('project_id, agent_id, environment_id required')
        if (!Number.isInteger(episodes) || Number(episodes) < 1 || Number(episodes) > 100000) return fail('episodes must be 1..100000')
        const { data, error } = await db.from('wf_runs').insert({ project_id, agent_id, environment_id,
          requested_episodes: episodes, config, status: 'queued' }).select().single()
        return error ? fail(error.message) : json(data, 201)
      }
      if (req.method === 'GET') {
        let query = db.from('wf_runs').select('*')
        if (id) query = query.eq('id', id)
        const { data, error } = await query
        return error ? fail(error.message) : json(id ? data?.[0] ?? null : { data })
      }
      if (req.method === 'PATCH' && id) {
        const status = body.status
        if (!['running', 'completed', 'failed', 'cancelled'].includes(String(status))) return fail('Invalid status')
        const { data, error } = await db.from('wf_runs').update({ status, finished_at: status === 'running' ? null : new Date().toISOString() }).eq('id', id).select().single()
        return error ? fail(error.message) : json(data)
      }
    }

    if (collection === 'episodes') {
      if (req.method === 'POST' && !id) {
        const { run_id, ordinal, seed, status, score, trace_object_key, error_code } = body
        if (typeof run_id !== 'string' || !Number.isInteger(ordinal) || !Number.isInteger(seed)) return fail('run_id, ordinal, seed required')
        const { data: parent, error: parentError } = await db.from('wf_runs').select('id,project_id,requested_episodes').eq('id', run_id).single()
        if (parentError || !parent) return fail('Unknown run', 404)
        if (Number(ordinal) < 0 || Number(ordinal) >= parent.requested_episodes) return fail('ordinal outside run')
        const { data, error } = await db.from('wf_episodes').insert({ run_id, ordinal, seed,
          status: status ?? 'completed', score, trace_object_key, error_code }).select().single()
        if (data && !error) await db.from('wf_usage').insert({ project_id: parent.project_id,
          run_id, episode_id: data.id, unit: 'episode', quantity: 1, source: 'client_reported' })
        return error ? fail(error.message) : json(data, 201)
      }
      if (id && subresource === 'trace' && req.method === 'POST') {
        if (!Array.isArray(body.events) || body.events.length > 10000) return fail('events array required (max 10000)')
        const { data: episode, error } = await db.from('wf_episodes').select('id,run_id').eq('id', id).single()
        if (error || !episode) return fail('Unknown episode', 404)
        const objectKey = `${auth.user.id}/${episode.run_id}/${id}.jsonl`
        const payload = body.events.map(event => JSON.stringify(event)).join('\n') + '\n'
        const { error: uploadError } = await db.storage.from('wf-traces').upload(objectKey,
          new Blob([payload], { type: 'application/x-ndjson' }), { upsert: false })
        if (uploadError) return fail(uploadError.message)
        const { error: updateError } = await db.from('wf_episodes').update({ trace_object_key: objectKey }).eq('id', id)
        return updateError ? fail(updateError.message) : json({ episode_id: id, trace_object_key: objectKey }, 201)
      }
      if (id && subresource === 'trace' && req.method === 'GET') {
        const { data: episode, error } = await db.from('wf_episodes').select('trace_object_key').eq('id', id).single()
        if (error || !episode?.trace_object_key) return fail('Trace not found', 404)
        const { data: file, error: downloadError } = await db.storage.from('wf-traces').download(episode.trace_object_key)
        return downloadError ? fail(downloadError.message, 404) : new Response(file, { headers: { 'Content-Type': 'application/x-ndjson' } })
      }
      if (req.method === 'GET') {
        let query = db.from('wf_episodes').select('*')
        if (id) query = query.eq('id', id)
        const { data, error } = await query
        return error ? fail(error.message) : json(id ? data?.[0] ?? null : { data })
      }
    }
    return fail('Unknown route', 404)
  } catch (error) {
    return fail(error instanceof Error ? error.message : 'Internal error', 500)
  }
})
