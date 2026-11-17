import { validateEnvironment, validateScenario, applyAction, grade } from './runtime.ts'

type Obj = Record<string, any>
type Caller = { ownerId: string, scopes: string[], boundProject: string | null, session: boolean }
type Service = {
  admin: any, caller: Caller, ownedProject: (caller: Caller, projectId: string) => Promise<boolean>,
  reply: (data: unknown, status?: number, headers?: HeadersInit) => Response,
  error: (message: string, status?: number) => Response,
}
const uuid = (x: unknown) => typeof x === 'string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(x)
const safeName = (name: unknown) => typeof name === 'string' &&
  name.length > 0 && name.length <= 160 && !/[\x00-\x1f/\\]/.test(name)
const publicEpisode = (row: Obj) => {
  const { trace_object_key: _private, ...safe } = row
  return safe
}
const publicArtifact = (row: Obj) => {
  const { storage_key: _private, ...safe } = row
  return safe
}
async function ownedManagedRun(s: Service, runId: string) {
  const { data, error } = await s.admin.from('wf_managed_runs').select('*').eq('id',runId).maybeSingle()
  if (error || !data || !(await s.ownedProject(s.caller,data.project_id))) return null
  return data
}
function verifyPlan(config: unknown, allowedActions: string[], maxSteps: number) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('Invalid agent')
  const plan = (config as Obj).plan
  if (!Array.isArray(plan) || plan.length < 1 || plan.length > maxSteps)
    throw new Error('Scripted agent requires 1..max_steps actions')
  for (const item of plan) {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        typeof item.action !== 'string' || !allowedActions.includes(item.action) ||
        (item.parameters !== undefined &&
          (!item.parameters || typeof item.parameters !== 'object' || Array.isArray(item.parameters))))
      throw new Error('Invalid scripted agent action')
  }
  return plan as { action: string, parameters?: Obj }[]
}

async function runScripted(s: Service, run: Obj, environment: Obj, scenario: Obj, agent: Obj) {
  const { admin } = s
  const env = validateEnvironment(environment)
  const checks = validateScenario(scenario)
  const plan = verifyPlan(agent,Object.keys(env.actions),run.max_steps)
  const claim = await admin.from('wf_managed_runs').update({
    status:'running',claimed_at:new Date().toISOString(),attempt_count:1,updated_at:new Date().toISOString(),
  }).eq('id',run.id).eq('status','queued').select('id').maybeSingle()
  if (claim.error) throw new Error('Could not claim run')
  if (!claim.data) return (await admin.from('wf_managed_runs').select('*').eq('id',run.id).single()).data

  let totalScore = 0, totalActions = 0, totalMs = 0
  try {
    for (let ordinal=0;ordinal<run.requested_episodes;ordinal++) {
      const started = performance.now()
      let state = structuredClone(env.initial_state)
      const events: Obj[] = [{type:'episode.started',ordinal,seed:run.seed+ordinal}]
      let actions=0
      for (const step of plan) {
        const next = applyAction(state,env,checks,step.action,step.parameters ?? {},actions+1)
        state = next.state
        actions++
        events.push({type:'agent.action',step:actions,action:step.action,
          parameters:step.parameters ?? {},observation:next.observation})
        for (const injected of next.events) events.push({type:'scenario.event',...injected})
      }
      const evaluation = grade(state,checks)
      const status = evaluation.passed ? 'passed' : 'failed'
      events.push({type:'episode.finished',status,checks:evaluation.checks,score:evaluation.score})
      const trace = events.map(item=>JSON.stringify(item)).join('\n')+'\n'
      const bytes = new TextEncoder().encode(trace).byteLength
      if (bytes>5_000_000) throw new Error('Trace exceeds limit')
      const key = run.project_id+'/managed/'+run.id+'/'+ordinal+'.jsonl'
      const { error: uploadError } = await admin.storage.from('wf-artifacts').upload(
        key,new Blob([trace],{type:'application/x-ndjson'}),{upsert:false})
      if (uploadError) throw new Error('Trace storage unavailable')
      const duration = Math.max(0,Math.round(performance.now()-started))
      const ep = await admin.from('wf_managed_episodes').insert({
        project_id:run.project_id,managed_run_id:run.id,ordinal,seed:run.seed+ordinal,
        status,score:evaluation.score,checks:evaluation.checks,action_count:actions,
        duration_ms:duration,trace_object_key:key,
      }).select('id').single()
      if (ep.error) throw new Error('Could not store episode')
      const artifact = await admin.from('wf_artifacts').insert({
        project_id:run.project_id,managed_run_id:run.id,kind:'trace',
        name:'episode-'+ordinal+'.jsonl',storage_key:key,bytes,content_type:'application/x-ndjson',
      })
      if (artifact.error) throw new Error('Could not register trace')
      totalScore+=evaluation.score
      totalActions+=actions
      totalMs+=duration
    }
    const usage = await admin.from('wf_managed_usage').insert({
      managed_run_id:run.id,project_id:run.project_id,
      episodes:run.requested_episodes,actions:totalActions,
      elapsed_ms:totalMs,source:'edge_verified',
    })
    if (usage.error) throw new Error('Could not record usage')
    const {data, error} = await admin.from('wf_managed_runs').update({
      status:'completed',completed_episodes:run.requested_episodes,
      score_mean:totalScore/run.requested_episodes,finished_at:new Date().toISOString(),
      updated_at:new Date().toISOString(),
    }).eq('id',run.id).eq('status','running').select('*').single()
    if (error) throw new Error('Could not complete run')
    return data
  } catch {
    await admin.from('wf_managed_runs').update({
      status:'failed',error_code:'execution_error',finished_at:new Date().toISOString(),
      updated_at:new Date().toISOString(),
    }).eq('id',run.id).eq('status','running')
    throw new Error('Managed execution failed')
  }
}

export async function handleManaged(
  req: Request, collection: string, id: string | undefined, subresource: string | undefined,
  body: Obj, service: Service,
): Promise<Response | null> {
  const {admin,caller,ownedProject,reply,error}=service
  const query=new URL(req.url).searchParams
  if (collection==='managed-runs') {
    if (!id && req.method==='POST') {
      const {project_id,environment_id,scenario_id,agent_id}=body
      if (![project_id,environment_id,scenario_id,agent_id].every(uuid) ||
          !(await ownedProject(caller,project_id))) return error('Unknown project or resources',404)
      const episodes=body.episodes??1
      const maxSteps=body.max_steps??30
      const executor=body.executor??'edge_scripted'
      const seed=body.seed??0
      if (executor!=='edge_scripted' && executor!=='cloud_tasks')return error('Unsupported execution backend')
      if (executor==='cloud_tasks' && Deno.env.get('WF_CLOUD_EXECUTION_ENABLED')!=='true')
        return error('Cloud workers are not configured',503)
      if (!Number.isSafeInteger(seed) || !Number.isInteger(episodes) ||
        !Number.isInteger(maxSteps) || (executor==='edge_scripted' && (episodes>5 || maxSteps>40)))
        return error('Invalid run limits')
      const key=body.idempotency_key??null
      if (key!==null && (typeof key!=='string'||!/^[A-Za-z0-9_-]{8,128}$/.test(key)))
        return error('Invalid idempotency key')
      const {data: resources, error: lookupError}=await admin.from('wf_resources')
        .select('id,kind,config').eq('project_id',project_id)
        .in('id',[environment_id,scenario_id,agent_id])
      if (lookupError) return error('Cannot load resources',503)
      const env=resources?.find((r:Obj)=>r.id===environment_id&&r.kind==='environment')
      const scenario=resources?.find((r:Obj)=>r.id===scenario_id&&r.kind==='scenario')
      const agent=resources?.find((r:Obj)=>r.id===agent_id&&r.kind==='agent')
      if(!env||!scenario||!agent) return error('Resources not found',404)
      try{
        const validated=validateEnvironment(env.config)
        validateScenario(scenario.config)
        verifyPlan(agent.config,Object.keys(validated.actions),maxSteps)
      }catch(e){ return error(e instanceof Error?e.message:'Invalid resource definition',400)}
      const {data: reserved,error:reserveError}=await admin.rpc('wf_reserve_managed_run',{
        p_project_id:project_id,p_environment_id:environment_id,p_scenario_id:scenario_id,
        p_agent_id:agent_id,p_episodes:episodes,p_max_steps:maxSteps,p_seed:seed,
        p_executor:executor,p_idempotency_key:key,
      })
      if(reserveError) return error('Could not reserve managed run',503)
      if(reserved?.error==='episode_quota_exceeded')return error('Monthly episode quota reached',429)
      if(reserved?.error) return error('Run rejected',400)
      const run=reserved.run
      if(reserved.duplicate||executor==='cloud_tasks')return reply(run,reserved.duplicate?200:202)
      try {
        return reply(await runScripted(service,run,env.config,scenario.config,agent.config),201)
      } catch { return error('Managed execution failed',503) }
    }
    if (!id && req.method==='GET') {
      const projectId=query.get('project_id')
      if(!projectId||!(await ownedProject(caller,projectId)))return error('Unknown project',404)
      const {data, error:dbError}=await admin.from('wf_managed_runs').select('*')
        .eq('project_id',projectId).order('created_at',{ascending:false}).limit(100)
      return dbError?error('Cannot list runs',503):reply({data})
    }
    if(!id||!uuid(id))return error('Run not found',404)
    const run=await ownedManagedRun(service,id)
    if(!run)return error('Run not found',404)
    if (req.method==='GET'&&!subresource)return reply(run)
    if (req.method==='GET'&&subresource==='episodes') {
      const {data,error:dbError}=await admin.from('wf_managed_episodes').select('*')
        .eq('managed_run_id',id).eq('project_id',run.project_id).order('ordinal')
      return dbError?error('Could not load episodes',503):reply({data:(data??[]).map(publicEpisode)})
    }
    if (req.method==='GET'&&subresource==='artifacts') {
      const {data,error:dbError}=await admin.from('wf_artifacts').select('*')
        .eq('managed_run_id',id).eq('project_id',run.project_id).order('created_at')
      return dbError?error('Could not list artifacts',503):reply({data:(data??[]).map(publicArtifact)})
    }
    return error('Not found',404)
  }
  if(collection==='artifacts') {
    if (!id&&req.method==='POST') {
      const projectId=body.project_id
      if(!uuid(projectId)||!(await ownedProject(caller,projectId)))return error('Unknown project',404)
      if(!safeName(body.name)||body.kind!=='dataset'||typeof body.content_base64!=='string'||
        body.content_base64.length>700000||!/^[A-Za-z0-9+/]*={0,2}$/.test(body.content_base64))
        return error('Invalid dataset (max 512 KiB encoded in base64)')
      let bytes:Uint8Array
      try {bytes=Uint8Array.from(atob(body.content_base64),c=>c.charCodeAt(0))}
      catch{return error('Invalid base64 content')}
      if(bytes.length>524288)return error('Dataset too large',413)
      const key=projectId+'/datasets/'+crypto.randomUUID()
      const {error:uploaded}=await admin.storage.from('wf-artifacts')
        .upload(key,new Blob([bytes],{type:'application/octet-stream'}),{upsert:false})
      if(uploaded)return error('Could not upload dataset',503)
      const {data,error:inserted}=await admin.from('wf_artifacts').insert({
        project_id:projectId,kind:'dataset',name:body.name,storage_key:key,
        bytes:bytes.length,content_type:'application/octet-stream',
      }).select('*').single()
      return inserted?error('Could not register dataset',503):reply(publicArtifact(data),201)
    }
    if (!id&&req.method==='GET') {
      const projectId=query.get('project_id')
      if (!projectId||!(await ownedProject(caller,projectId)))return error('Unknown project',404)
      const {data,error:dbError}=await admin.from('wf_artifacts').select('*')
        .eq('project_id',projectId).order('created_at',{ascending:false}).limit(100)
      return dbError?error('Could not list artifacts',503):reply({data:(data??[]).map(publicArtifact)})
    }
    if(!id||!uuid(id)||req.method!=='GET'||subresource!=='download')
      return error('Artifact not found',404)
    const {data:artifact,error:dbError}=await admin.from('wf_artifacts').select('*')
      .eq('id',id).maybeSingle()
    if(dbError||!artifact||!(await ownedProject(caller,artifact.project_id)))
      return error('Artifact not found',404)
    const {data:signed,error:signError}=await admin.storage.from('wf-artifacts')
      .createSignedUrl(artifact.storage_key,60)
    return signError?error('Could not access artifact',503):
      reply({url:signed.signedUrl,expires_in:60})
  }
  if(collection==='billing') {
    const projectId=(req.method==='GET'?query.get('project_id'):body.project_id)
    if(!projectId||!uuid(projectId)||!(await ownedProject(caller,projectId)))
      return error('Unknown project',404)
    if(req.method==='GET'&&id==='entitlement'){
      const {data,error:dbError}=await admin.from('wf_billing_customers')
        .select('plan,subscription_status,monthly_episode_limit,updated_at')
        .eq('project_id',projectId).maybeSingle()
      return dbError?error('Could not read entitlement',503):
        reply(data??{plan:'free',subscription_status:'inactive',monthly_episode_limit:20})
    }
    if(req.method==='GET'&&id==='usage'){
      const {data,error:dbError}=await admin.from('wf_managed_runs')
        .select('requested_episodes,status').eq('project_id',projectId)
        .gte('created_at',new Date(new Date().getFullYear(),new Date().getMonth(),1).toISOString())
      if(dbError)return error('Could not read usage',503)
      return reply({month_episodes_reserved:(data??[])
        .filter((r:Obj)=>r.status!=='cancelled')
        .reduce((n:number,r:Obj)=>n+r.requested_episodes,0)})
    }
    if(req.method==='POST'&&id==='checkout'){
      const serviceUrl=Deno.env.get('WF_BILLING_SERVICE_URL')
      const token=Deno.env.get('WF_BILLING_SHARED_TOKEN')
      if(!serviceUrl||!token)return error('Billing checkout is not configured',503)
      if(!/^https:\/\/[a-z0-9.-]+(?:\/[a-z0-9/_-]*)?$/i.test(serviceUrl))
        return error('Billing configuration error',503)
      try {
        const upstream=await fetch(serviceUrl.replace(/\/$/,'')+'/billing/checkout',{
          method:'POST',headers:{'Content-Type':'application/json','x-wf-internal-token':token},
          body:JSON.stringify({project_id:projectId,owner_id:caller.ownerId}),
          signal:AbortSignal.timeout(10000),
        })
        if(!upstream.ok)return error('Billing checkout unavailable',503)
        const value=await upstream.json()
        if(typeof value?.url!=='string'||!value.url.startsWith('https://checkout.stripe.com/'))
          return error('Billing checkout unavailable',503)
        return reply({url:value.url})
      }catch {return error('Billing checkout unavailable',503)}
    }
    return error('Not found',404)
  }
  if(collection==='connectors'&&req.method==='GET'&&!id)
    return reply({data:[{id:'json_snapshot',mode:'import_only',live_writes:false}]})
  return null
}
