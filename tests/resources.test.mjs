import assert from 'node:assert/strict'
import {randomUUID} from 'node:crypto'
import {test} from 'node:test'
import {handleResources} from '../supabase/functions/worldfoundry-customer-api/resources.ts'

const projectA=randomUUID(),projectB=randomUUID()
const tables={
  wf_projects:[{id:projectA,owner_id:'alice'},{id:projectB,owner_id:'bob'}],
  wf_resources:[], wf_resource_revisions:[],
}
class Query{
  constructor(name){this.name=name;this.filters=[];this.field='*';this.mode='select';this.limitValue=null;this.rangeValue=null;this.orderings=[]}
  select(field='*'){this.field=field;return this}
  eq(key,val){this.filters.push(row=>row[key]===val);return this}
  in(key,vals){this.filters.push(row=>vals.includes(row[key]));return this}
  is(key,val){this.filters.push(row=>row[key]===val);return this}
  limit(n){this.limitValue=n;return this}
  order(key,{ascending=true}={}){this.orderings.push({key,ascending});return this}
  range(from,to){this.rangeValue=[from,to];return this}
  insert(value){this.mode='insert';this.value=value;return this}
  rows(){
    if(this.mode==='insert'){
      const now=new Date().toISOString()
      const row={id:randomUUID(),created_at:now,updated_at:now,archived_at:null,...this.value}
      tables[this.name].push(row)
      if(this.name==='wf_resources')archiveRevision(row)
      return [row]
    }
    let rows=tables[this.name].filter(row=>this.filters.every(fn=>fn(row)))
    for(const {key,ascending} of [...this.orderings].reverse()){
      rows=rows.toSorted((x,y)=>x[key]<y[key]?(ascending?-1:1):x[key]>y[key]?(ascending?1:-1):0)
    }
    if(this.rangeValue)rows=rows.slice(this.rangeValue[0],this.rangeValue[1]+1)
    if(this.limitValue!=null)rows=rows.slice(0,this.limitValue)
    if(this.field==='*')return rows
    const cols=this.field.split(',')
    return rows.map(row=>Object.fromEntries(cols.map(col=>[col,row[col]])))
  }
  then(fn){return Promise.resolve({data:this.rows(),error:null}).then(fn)}
  maybeSingle(){return Promise.resolve({data:this.rows()[0]??null,error:null})}
  single(){return this.maybeSingle()}
}
function archiveRevision(row){
  tables.wf_resource_revisions.push({
    resource_id:row.id,project_id:row.project_id,kind:row.kind,
    version:row.version,name:row.name,config:structuredClone(row.config),
    archived_at:row.archived_at,created_at:new Date().toISOString(),
  })
}
const admin={
  from(table){assert.ok(Object.hasOwn(tables,table),table);return new Query(table)},
  async rpc(name,values){
    assert.equal(name,'wf_resource_change')
    const row=tables.wf_resources.find(r=>r.id===values.p_resource_id&&
      r.kind===values.p_kind&&r.project_id===values.p_project_id)
    if(!row)return {data:{error:'not_found'},error:null}
    if(row.version!==values.p_expected_version)
      return {data:{error:'conflict',current_version:row.version},error:null}
    if(values.p_name!=null)row.name=values.p_name
    if(values.p_config!=null)row.config=structuredClone(values.p_config)
    if(values.p_archive===true)row.archived_at=new Date().toISOString()
    else if(values.p_archive===false)row.archived_at=null
    row.version++
    row.updated_at=new Date().toISOString()
    archiveRevision(row)
    return {data:{resource:structuredClone(row)},error:null}
  }
}
async function call(collection,method='GET',body={},id,subresource,detail,owner='alice',query=''){
  const path=[collection,id,subresource,detail].filter(Boolean).join('/')+(query?'?'+query:'')
  const req=new Request('https://api.worldfoundry.example/v1/'+path,{
    method,headers:{'content-type':'application/json'},
    body:['POST','PATCH'].includes(method)?JSON.stringify(body):undefined,
  })
  const caller={ownerId:owner,scopes:['read','write'],boundProject:null,session:false}
  const result=await handleResources(req,collection,id,subresource,detail,body,{
    admin,caller,
    ownedProject:async(c,project)=>tables.wf_projects.some(p=>
      p.id===project&&p.owner_id===c.ownerId&&
      (!c.boundProject||c.boundProject===project)),
    reply:(data,status=200)=>Response.json(data,{status}),
    error:(message,status=400)=>Response.json({error:message},{status}),
  })
  assert.ok(result,'Handler ignored valid resource type')
  return {status:result.status,data:await result.json()}
}
test('user-defined reusable template, copy-on-create, version conflicts and archive/restore',async()=>{
  const def={instruction:'Ship an order',initial_state:{order:{status:'pending'}},
    actions:{ship:{operation:'set',path:'order.status',value:'shipped'}}}
  const created=await call('templates','POST',{project_id:projectA,name:'Order template',config:def})
  assert.equal(created.status,201)
  assert.equal(created.data.version,1)
  const from=await call('environments','POST',{project_id:projectA,name:'Warehouse lab',
    template_id:created.data.id,overrides:{initial_state:{order:{status:'held'}}}})
  assert.equal(from.status,201)
  assert.equal(from.data.config.initial_state.order.status,'held')
  assert.equal(from.data.config._wf_source_template.version,1)
  const updated=await call('templates','PATCH',{expected_version:1,config:{
    ...def,instruction:'Revised instructions',
  }},created.data.id)
  assert.equal(updated.status,200)
  assert.equal(updated.data.version,2)
  assert.equal(from.data.config.instruction,'Ship an order')
  const conflict=await call('templates','PATCH',{expected_version:1,name:'Overwritten'},
    created.data.id)
  assert.equal(conflict.status,409)
  assert.equal(conflict.data.current_version,2)
  const first=await call('templates','GET',{},created.data.id,'versions','1')
  assert.equal(first.data.config.instruction,'Ship an order')
  const versions=await call('templates','GET',{},created.data.id,'versions')
  assert.equal(versions.data.data.length,2)
  const archived=await call('templates','POST',{expected_version:2},created.data.id,'archive')
  assert.equal(archived.data.version,3)
  const list=await call('templates','GET',{},undefined,undefined,undefined,'alice',
    'project_id='+projectA)
  assert.equal(list.data.data.some(x=>x.id===created.data.id),false)
  const byId=await call('templates','GET',{},created.data.id)
  assert.equal(byId.status,200)
  const restored=await call('templates','POST',
    {expected_version:3,version:1},created.data.id,'restore')
  assert.equal(restored.data.version,4)
  assert.equal(restored.data.archived_at,null)
  assert.equal(restored.data.config.instruction,'Ship an order')
  assert.equal(tables.wf_resource_revisions.filter(x=>x.resource_id===created.data.id).length,4)
})
test('tenant-scoped access and cross-project template instantiation are rejected',async()=>{
  const template=tables.wf_resources.find(x=>x.kind==='template')
  const alien=await call('templates','GET',{},template.id,undefined,undefined,'bob')
  assert.equal(alien.status,404)
  const transplant=await call('environments','POST',{project_id:projectB,name:'Not mine',
    template_id:template.id})
  assert.equal(transplant.status,404)
  const crossGet=await call('environments','GET',{},undefined,undefined,undefined,'bob',
    'project_id='+projectA)
  assert.equal(crossGet.status,404)
  const noPermission=await call('templates','POST',
    {project_id:projectB,name:'Wrong owner',config:{}},undefined,undefined,undefined,'alice')
  assert.equal(noPermission.status,404)
})
test('unbounded resource collection is accessed through stable paginated pages',async()=>{
  for(let i=0;i<126;i++){
    const result=await call('workflows','POST',{
      project_id:projectA,name:'Workflow '+i,config:{workflow_id:i,steps:[i]},
    })
    assert.equal(result.status,201)
  }
  const found=new Set()
  let offset=0,pages=0
  while(true){
    const page=await call('workflows','GET',{},undefined,undefined,undefined,'alice',
      'project_id='+projectA+'&limit=50&offset='+offset)
    assert.equal(page.status,200)
    for(const resource of page.data.data)found.add(resource.id)
    pages++
    if(page.data.next_offset===null)break
    offset=page.data.next_offset
  }
  assert.equal(found.size,126)
  assert.equal(pages,3)
  assert.equal((await call('workflows','GET',{},undefined,undefined,undefined,'bob',
    'project_id='+projectB)).data.data.length,0)
})
