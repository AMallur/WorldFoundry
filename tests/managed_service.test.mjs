import assert from 'node:assert/strict'
import {randomUUID} from 'node:crypto'
import {test} from 'node:test'
import {handleManaged} from '../supabase/functions/worldfoundry-customer-api/managed.ts'

const IDS = {
  one:'11111111-1111-4111-8111-111111111111',
  two:'22222222-2222-4222-8222-222222222222',
  env:'33333333-3333-4333-8333-333333333333',
  scenario:'44444444-4444-4444-8444-444444444444',
  agent:'55555555-5555-4555-8555-555555555555',
}
const tables={
  wf_resources:[
    {id:IDS.env,project_id:IDS.one,kind:'environment',config:{
      instruction:'Resolve a ticket',initial_state:{tickets:{T1:{status:'open'}}},
      actions:{resolve:{operation:'set',path:'tickets.$id.status',value:'closed',
        parameters:{id:{type:'string'}}}},
    }},
    {id:IDS.scenario,project_id:IDS.one,kind:'scenario',
      config:{checks:[{name:'closed',path:'tickets.T1.status',equals:'closed'}]}},
    {id:IDS.agent,project_id:IDS.one,kind:'agent',
      config:{plan:[{action:'resolve',parameters:{id:'T1'}}]}},
  ],
  wf_managed_runs:[],wf_managed_episodes:[],wf_managed_usage:[],
  wf_artifacts:[],wf_billing_customers:[],
}
const bucket=new Map()
class Query {
  constructor(name) {this.name=name;this.filters=[];this.mode='select';this.columns='*'}
  select(columns='*'){this.columns=columns;return this}
  eq(k,v){this.filters.push(row=>row[k]===v);return this}
  gte(k,v){this.filters.push(row=>row[k]>=v);return this}
  in(k,v){this.filters.push(row=>v.includes(row[k]));return this}
  order(){return this}
  limit(){return this}
  insert(values){this.mode='insert';this.values=values;return this}
  update(values){this.mode='update';this.values=values;return this}
  rows(){
    let rows
    if(this.mode==='insert'){
      const row={id:randomUUID(),created_at:new Date().toISOString(),...this.values}
      tables[this.name].push(row);rows=[row]
    }else{
      rows=tables[this.name].filter(row=>this.filters.every(f=>f(row)))
      if(this.mode==='update')rows.forEach(row=>Object.assign(row,this.values))
    }
    if(this.columns==='*')return rows
    return rows.map(row=>Object.fromEntries(this.columns.split(',').map(k=>[k,row[k]])))
  }
  then(fn){return Promise.resolve({data:this.rows(),error:null}).then(fn)}
  maybeSingle(){return Promise.resolve({data:this.rows()[0]??null,error:null})}
  single(){return this.maybeSingle()}
}
const admin={
  from(name){if(!tables[name])throw Error('Table not mocked: '+name);return new Query(name)},
  storage:{from(name){assert.equal(name,'wf-artifacts');return {
    async upload(key,content){bucket.set(key,content);return {error:null}},
    async createSignedUrl(key){return {data:{signedUrl:'https://storage.test/'+key},error:null}},
  }}},
  async rpc(name,params){
    assert.equal(name,'wf_reserve_managed_run')
    const existing=tables.wf_managed_runs.find(row=>row.idempotency_key===params.p_idempotency_key)
    if(existing)return {data:{run:existing,duplicate:true},error:null}
    const row={id:randomUUID(),project_id:params.p_project_id,
      environment_id:params.p_environment_id,scenario_id:params.p_scenario_id,
      agent_id:params.p_agent_id,requested_episodes:params.p_episodes,
      max_steps:params.p_max_steps,seed:params.p_seed,executor:params.p_executor,
      idempotency_key:params.p_idempotency_key,attempt_count:0,
      status:'queued',created_at:new Date().toISOString()}
    tables.wf_managed_runs.push(row)
    return {data:{run:row,duplicate:false},error:null}
  },
}
async function call(path,method='GET',body={},owner=IDS.one){
  const pieces=path.split('?')[0].split('/').filter(Boolean)
  const url='https://worldfoundry.test/v1/'+path
  const request=new Request(url,{method,
    headers:{'Content-Type':'application/json'},
    body:method==='POST'?JSON.stringify(body):undefined})
  const caller={ownerId:owner,scopes:['read','write'],boundProject:null,session:false}
  return handleManaged(request,pieces[0],pieces[1],pieces[2],body,{
    admin,caller,ownedProject:async(_,id)=>id===owner,
    reply:(data,status=200)=>Response.json(data,{status}),
    error:(msg,status=400)=>Response.json({error:msg},{status}),
  })
}
test('managed job executes and persists scores, traces and metering',async()=>{
  const body={project_id:IDS.one,environment_id:IDS.env,
    scenario_id:IDS.scenario,agent_id:IDS.agent,
    episodes:2,idempotency_key:'jobtest-001'}
  const result=await call('managed-runs','POST',body)
  assert.equal(result.status,201,await result.clone().text())
  const run=await result.json()
  assert.equal(run.status,'completed')
  assert.equal(run.score_mean,1)
  assert.equal(tables.wf_managed_episodes.length,2)
  assert.equal(tables.wf_managed_usage.length,1)
  assert.equal(tables.wf_managed_usage[0].actions,2)
  assert.equal(bucket.size,2)
  const episodes=await call('managed-runs/'+run.id+'/episodes')
  assert.equal((await episodes.json()).data.length,2)
  const artifacts=await call('managed-runs/'+run.id+'/artifacts')
  assert.equal((await artifacts.json()).data.length,2)
  const repeated=await call('managed-runs','POST',body)
  assert.equal(repeated.status,200)
  assert.equal(tables.wf_managed_runs.length,1)
  const signed=await call('artifacts/'+tables.wf_artifacts[0].id+'/download')
  assert.equal(signed.status,200)
  assert.equal((await signed.json()).expires_in,60)
})
test('managed resources are tenant-bound and sensitive storage keys stay private',async()=>{
  const other=await call('managed-runs','POST',{
    project_id:IDS.two,environment_id:IDS.env,
    scenario_id:IDS.scenario,agent_id:IDS.agent,
  })
  assert.equal(other.status,404)
  const forbidden=await call('managed-runs/'+tables.wf_managed_runs[0].id,'GET',{},IDS.two)
  assert.equal(forbidden.status,404)
  const owned=await call('artifacts?project_id='+IDS.one)
  assert.equal(owned.status,200)
  const artifacts=await owned.json()
  assert.equal(Object.hasOwn(artifacts.data[0],'storage_key'),false)
})
test('cloud compute and checkout fail closed when disabled or unconfigured',async()=>{
  const cloud=await call('managed-runs','POST',{
    project_id:IDS.one,environment_id:IDS.env,
    scenario_id:IDS.scenario,agent_id:IDS.agent,executor:'cloud_tasks',
  })
  assert.equal(cloud.status,503)
  const checkout=await call('billing/checkout','POST',{project_id:IDS.one})
  assert.equal(checkout.status,503)
})
