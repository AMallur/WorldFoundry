// WorldFoundry's hosted, company-controlled user resource library.
// Supabase service credentials remain exclusively in the authenticated API.
// Public Python clients receive ONLY their own WorldFoundry API keys.
type Row = Record<string, any>
type Caller = { ownerId: string, scopes: string[], boundProject: string | null, session: boolean }
type Service = {
  admin: any
  caller: Caller
  ownedProject: (caller: Caller, projectId: string) => Promise<boolean>
  reply: (data: unknown, status?: number) => Response
  error: (message: string, status?: number) => Response
}
export const resourceKinds: Record<string,string> = {
  templates: 'template', environments:'environment', scenarios:'scenario',
  agents:'agent',datasets:'dataset',policies:'policy',validators:'validator',
  tools:'tool',workflows:'workflow',applications:'application',
}
const uuid = (s: unknown): s is string =>
  typeof s==='string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s)
const plain = (o: unknown): o is Row =>
  !!o && typeof o==='object' && !Array.isArray(o)
const maxBytes = 131072
function validConfig(config: unknown): config is Row {
  if (!plain(config)) return false
  try { return new TextEncoder().encode(JSON.stringify(config)).length<=maxBytes }
  catch { return false }
}
const validName = (s: unknown): s is string =>
  typeof s==='string' && !!s.trim() && s.length<=160
function page(query: URLSearchParams): {limit:number,offset:number}|null {
  const rawLimit=query.get('limit')??'50'
  const rawOffset=query.get('offset')??'0'
  if (!/^\d+$/.test(rawLimit)|| !/^\d+$/.test(rawOffset))return null
  const limit=Number(rawLimit), offset=Number(rawOffset)
  return Number.isSafeInteger(limit) && limit>=1 && limit<=100 &&
    Number.isSafeInteger(offset) && offset>=0 && offset<=Number.MAX_SAFE_INTEGER ?
    {limit,offset}:null
}
function merge(target: Row, overrides: Row, depth=0): Row {
  if(depth>12)throw Error('Template nesting too deep')
  const result=structuredClone(target)
  for(const [key,value] of Object.entries(overrides)){
    if(['__proto__','constructor','prototype'].includes(key))throw Error('Unsafe template field')
    if(plain(value)&&plain(result[key]))result[key]=merge(result[key],value,depth+1)
    else result[key]=structuredClone(value)
  }
  return result
}
async function change(s: Service, resource: Row, expectedVersion: number,
                      name: string|null=null,config: Row|null=null,archive:boolean|null=null)
:Promise<Response>{
  const {data,error:failure}=await s.admin.rpc('wf_resource_change',{
    p_resource_id:resource.id,p_project_id:resource.project_id,
    p_kind:resource.kind,p_expected_version:expectedVersion,
    p_name:name,p_config:config,p_archive:archive,
  })
  if(failure)return s.error('Resource update unavailable',503)
  if(data?.error==='conflict')return s.reply(
    {error:'Version conflict',current_version:data.current_version},409)
  if(data?.error)return s.error('Cannot update resource: '+data.error,400)
  return s.reply(data.resource)
}
async function ownedResource(s:Service,id:string,kind:string):Promise<Row|null>{
  if(!uuid(id))return null
  const {data,error:failure}=await s.admin.from('wf_resources')
    .select('*').eq('id',id).eq('kind',kind).maybeSingle()
  if(failure||!data||!(await s.ownedProject(s.caller,data.project_id)))return null
  return data
}

export async function handleResources(
  req:Request, collection:string, id:string|undefined, subresource:string|undefined,
  detail:string|undefined, body:Row, s:Service
):Promise<Response|null>{
  const kind=resourceKinds[collection]
  if(!kind)return null
  const {admin,caller,ownedProject,reply,error}=s
  const args=new URL(req.url).searchParams

  if(!id && req.method==='POST'){
    const projectId=body.project_id
    if(!uuid(projectId)||!(await ownedProject(caller,projectId)))
      return error('Unknown project',404)
    if(!validName(body.name))return error('Resource name must be 1..160 characters')
    // The library's version is server-owned; customers never choose an
    // arbitrary version or pass an infrastructure credential.
    if('version' in body&&body.version!==1)return error('Initial version must be 1')
    let config:Row
    const {project_id:_project,name:_name,config:provided,
      version:_version,template_id:templateId,template_version:templateVersion,
      overrides,...flat}=body
    if(templateId!==undefined){
      if(kind!=='environment'||!uuid(templateId)||provided!==undefined ||
         Object.keys(flat).length)return error('Invalid environment template creation')
      const {data:template, error:lookError}=await admin.from('wf_resources')
        .select('id,project_id,kind,version,config,archived_at')
        .eq('id',templateId).eq('project_id',projectId).eq('kind','template').maybeSingle()
      if(lookError)return error('Template lookup unavailable',503)
      if(!template||template.archived_at)return error('Template not found',404)
      let sourceConfig=template.config
      let pinnedVersion=template.version
      if(templateVersion!==undefined){
        if(!Number.isInteger(templateVersion)||templateVersion<=0)
          return error('Invalid template version')
        const {data:revision,error:revError}=await admin.from('wf_resource_revisions')
          .select('version,config').eq('resource_id',templateId)
          .eq('project_id',projectId).eq('version',templateVersion).maybeSingle()
        if(revError)return error('Template revision unavailable',503)
        if(!revision)return error('Template revision not found',404)
        sourceConfig=revision.config;pinnedVersion=revision.version
      }
      if(overrides!==undefined&&!plain(overrides))return error('Template overrides must be an object')
      try{
        config=merge(sourceConfig,overrides??{})
        config._wf_source_template={id:templateId,version:pinnedVersion}
      }catch{return error('Invalid template overrides')}
    }else{
      if(templateVersion!==undefined||overrides!==undefined)
        return error('template_version and overrides require template_id')
      config=provided!==undefined?provided:flat
      if(provided!==undefined&&Object.keys(flat).length)
        return error('Use config or top-level fields, not both')
    }
    if(!validConfig(config))return error('Configuration must be a JSON object (max 128 KiB)',413)
    const {data,error:dbError}=await admin.from('wf_resources').insert({
      project_id:projectId,kind,name:body.name.trim(),config,version:1,
    }).select('*').single()
    return dbError?error('Could not create resource',503):reply(data,201)
  }

  if(!id&&req.method==='GET'){
    const paging=page(args)
    if(!paging)return error('limit must be 1..100, offset must be a nonnegative safe integer')
    const projectId=args.get('project_id')
    let allowed:string[]
    if(projectId){
      if(!uuid(projectId)||!(await ownedProject(caller,projectId)))
        return error('Unknown project',404)
      allowed=[projectId]
    }else{
      // Legacy all-project listing. Use project_id for complete pagination
      // when the company owns very many projects.
      const {data,error:projectsError}=await admin.from('wf_projects').select('id')
        .eq('owner_id',caller.ownerId).limit(1000)
      if(projectsError)return error('Could not load projects',503)
      allowed=(projects??[]).map((p:Row)=>p.id)
        .filter((p:string)=>!caller.boundProject||caller.boundProject===p)
      if(!allowed.length)return reply({data:[],next_offset:null})
    }
    let q=admin.from('wf_resources').select('*')
      .eq('kind',kind).in('project_id',allowed)
    if(args.get('include_archived')!=='true')q=q.is('archived_at',null)
    const {data,error:dbError}=await q.order('created_at',{ascending:false})
      .order('id',{ascending:false}).range(paging.offset,paging.offset+paging.limit)
    if(dbError)return error('Could not list resources',503)
    const items=data??[]
    const hasNext=items.length>paging.limit
    return reply({data:items.slice(0,paging.limit),
      next_offset:hasNext?paging.offset+paging.limit:null})
  }

  if(!id)return error('Not found',404)
  const resource=await ownedResource(s,id,kind)
  if(!resource)return error('Resource not found',404)
  if(req.method==='GET'&&!subresource)return reply(resource)

  if(req.method==='GET'&&subresource==='versions'){
    if(detail!==undefined){
      if(!/^[1-9]\d*$/.test(detail))return error('Invalid resource version')
      const version=Number(detail)
      const {data,error:dbError}=await admin.from('wf_resource_revisions')
        .select('resource_id,project_id,kind,version,name,config,archived_at,created_at')
        .eq('resource_id',resource.id).eq('project_id',resource.project_id)
        .eq('version',version).maybeSingle()
      return dbError?error('Could not read revision',503):data?
        reply(data):error('Revision not found',404)
    }
    const paging=page(args)
    if(!paging)return error('Invalid pagination')
    const {data,error:dbError}=await admin.from('wf_resource_revisions')
      .select('resource_id,project_id,kind,version,name,config,archived_at,created_at')
      .eq('resource_id',resource.id).eq('project_id',resource.project_id)
      .order('version',{ascending:false}).range(paging.offset,paging.offset+paging.limit)
    if(dbError)return error('Could not list revisions',503)
    const rows=data??[],hasNext=rows.length>paging.limit
    return reply({data:rows.slice(0,paging.limit),
      next_offset:hasNext?paging.offset+paging.limit:null})
  }

  if(req.method==='PATCH'&&!subresource){
    const expected=body.expected_version
    if(!Number.isInteger(expected)||expected<1)return error('expected_version is required')
    if(!('name'in body)&&!('config'in body))return error('name or config is required')
    if(Object.keys(body).some(k=>!['expected_version','name','config'].includes(k)))
      return error('Unknown update field')
    if('name'in body&&!validName(body.name))return error('Invalid resource name')
    if('config'in body&&!validConfig(body.config))return error('Invalid config',413)
    return change(s,resource,expected,body.name??null,body.config??null)
  }
  if(req.method==='POST'&&['archive','unarchive','restore'].includes(subresource)
     &&detail===undefined){
    const expected=body.expected_version
    if(!Number.isInteger(expected)||expected<1)return error('expected_version required')
    if(subresource==='archive')return change(s,resource,expected,null,null,true)
    if(subresource==='unarchive')return change(s,resource,expected,null,null,false)
    const version=body.version
    if(!Number.isInteger(version)||version<1)return error('version required')
    const {data:previous,error:revError}=await admin.from('wf_resource_revisions')
      .select('name,config,archived_at')
      .eq('resource_id',resource.id).eq('project_id',resource.project_id)
      .eq('version',version).maybeSingle()
    if(revError)return error('Revision unavailable',503)
    if(!previous)return error('Revision not found',404)
    return change(s,resource,expected,previous.name,previous.config,
      previous.archived_at!==null)
  }
  return error('Not found',404)
}
