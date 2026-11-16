/**
 * WorldFoundry deterministic, declarative simulation interpreter.
 * No arbitrary user JavaScript, HTTP calls, eval, or access to live integrations.
 * The control plane persists each transition with an atomic database RPC.
 */
export type PlainObject = Record<string, unknown>
export type ActionDefinition = {
  operation: 'read' | 'set' | 'append' | 'increment'
  path: string
  parameters?: Record<string, { type: 'string' | 'number' | 'boolean' | 'object', enum?: unknown[] }>
  value?: unknown
  from_param?: string
}
export type EnvironmentDefinition = {
  initial_state: PlainObject
  actions: Record<string, ActionDefinition>
  instruction?: string
}
export type ScenarioDefinition = {
  checks: { name: string, path: string, equals: unknown }[]
  events?: { at_step: number, operation: 'set' | 'append' | 'increment',
    path: string, value: unknown }[]
}
const forbidden = new Set(['__proto__', 'prototype', 'constructor'])
const plain = (x: unknown): x is PlainObject =>
  x !== null && typeof x === 'object' && !Array.isArray(x)
const copy = <T>(x: T): T => structuredClone(x)
const size = (x: unknown): number => new TextEncoder().encode(JSON.stringify(x)).length
function validPath(path: unknown, allowParameters: boolean): boolean {
  if (typeof path !== 'string' || !path || path.length > 256) return false
  return path.split('.').every(part => {
    const name = allowParameters && part.startsWith('$') ? part.slice(1) : part
    return /^[a-zA-Z0-9_-]{1,80}$/.test(name) && !forbidden.has(name)
  })
}
export function validateEnvironment(value: unknown): EnvironmentDefinition {
  if (!plain(value) || !plain(value.initial_state) || size(value.initial_state) > 65536 ||
    !plain(value.actions) || Object.keys(value.actions).length === 0 ||
    Object.keys(value.actions).length > 64) throw new Error('Invalid environment state or actions')
  for (const [name, raw] of Object.entries(value.actions)) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(name) || !plain(raw) ||
      !['read', 'set', 'append', 'increment'].includes(String(raw.operation)) ||
      !validPath(raw.path, true)) throw new Error('Invalid action definition: ' + name)
    if (raw.parameters !== undefined && (!plain(raw.parameters) ||
      Object.keys(raw.parameters).length > 16)) throw new Error('Invalid action parameters')
    for (const [param, spec] of Object.entries((raw.parameters ?? {}) as PlainObject)) {
      if (!/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(param) || !plain(spec) ||
        !['string', 'number', 'boolean', 'object'].includes(String(spec.type)) ||
        (spec.enum !== undefined && (!Array.isArray(spec.enum) || spec.enum.length > 32)))
        throw new Error('Invalid parameter schema')
    }
    const vars = String(raw.path).split('.').filter(x => x.startsWith('$')).map(x => x.slice(1))
    if (vars.some(v => !Object.hasOwn(raw.parameters ?? {}, v))) throw new Error('Path parameter not declared')
    if (raw.from_param !== undefined && (typeof raw.from_param !== 'string' ||
      !Object.hasOwn(raw.parameters ?? {}, raw.from_param))) throw new Error('Value parameter not declared')
  }
  if (value.instruction !== undefined && (typeof value.instruction !== 'string' ||
    value.instruction.length > 4000)) throw new Error('Invalid instruction')
  return value as EnvironmentDefinition
}
export function validateScenario(value: unknown): ScenarioDefinition {
  if (!plain(value) || !Array.isArray(value.checks) || value.checks.length < 1 ||
    value.checks.length > 64 || (value.events !== undefined && (!Array.isArray(value.events) ||
      value.events.length > 64))) throw new Error('Invalid scenario checks or events')
  for (const check of value.checks) {
    if (!plain(check) || typeof check.name !== 'string' ||
      !/^[a-zA-Z0-9_-]{1,80}$/.test(check.name) ||
      !validPath(check.path, false) || !Object.hasOwn(check, 'equals'))
      throw new Error('Invalid scenario check')
  }
  for (const event of value.events ?? []) {
    if (!plain(event) || !Number.isInteger(event.at_step) ||
      event.at_step < 1 || event.at_step > 1000 ||
      !['set', 'append', 'increment'].includes(String(event.operation)) ||
      !validPath(event.path, false) || !Object.hasOwn(event, 'value'))
      throw new Error('Invalid scenario event')
  }
  if (size(value) > 65536) throw new Error('Scenario too large')
  return value as ScenarioDefinition
}
function pathSegments(path: string, params: PlainObject): string[] {
  return path.split('.').map(p => {
    const name = p.startsWith('$') ? params[p.slice(1)] : p
    if (typeof name !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(name) ||
      forbidden.has(name)) throw new Error('Unsafe or missing path segment')
    return name
  })
}
function location(state: PlainObject, segments: string[]): { parent: PlainObject, key: string } {
  let cursor: unknown = state
  for (const segment of segments.slice(0, -1)) {
    if (!plain(cursor) || !Object.hasOwn(cursor, segment)) throw new Error('Unknown state path')
    cursor = cursor[segment]
  }
  const key = segments[segments.length - 1]
  if (!plain(cursor) || !Object.hasOwn(cursor, key)) throw new Error('Unknown state path')
  return { parent: cursor, key }
}
function change(state: PlainObject, operation: string, path: string, value: unknown,
  params: PlainObject): unknown {
  const { parent, key } = location(state, pathSegments(path, params))
  if (operation === 'read') return copy(parent[key])
  if (operation === 'set') parent[key] = copy(value)
  else if (operation === 'append') {
    if (!Array.isArray(parent[key]) || (parent[key] as unknown[]).length >= 1000)
      throw new Error('Target is not an appendable array')
    ;(parent[key] as unknown[]).push(copy(value))
  } else if (operation === 'increment') {
    if (typeof parent[key] !== 'number' || typeof value !== 'number' ||
      !Number.isFinite(value)) throw new Error('Increment requires finite numbers')
    const n = (parent[key] as number) + value
    if (!Number.isFinite(n)) throw new Error('Numeric overflow')
    parent[key] = n
  }
  if (size(state) > 65536) throw new Error('State exceeds 64 KiB')
  return copy(parent[key])
}
export function applyAction(state: PlainObject, env: EnvironmentDefinition,
  scenario: ScenarioDefinition, actionName: string, parameters: PlainObject,
  nextStep: number): { state: PlainObject, observation: unknown, events: PlainObject[] } {
  const action = env.actions[actionName]
  if (!action) throw new Error('Unknown action')
  if (!plain(parameters) || Object.keys(parameters).length > 16) throw new Error('Invalid parameters')
  const specs = action.parameters ?? {}
  for (const [name, spec] of Object.entries(specs)) {
    if (!Object.hasOwn(parameters, name)) throw new Error('Missing parameter: ' + name)
    const value = parameters[name]
    if (spec.type === 'object' ? !plain(value) : typeof value !== spec.type)
      throw new Error('Wrong parameter type: ' + name)
    if (spec.enum && !spec.enum.some(item => JSON.stringify(item) === JSON.stringify(value)))
      throw new Error('Parameter outside allowed values: ' + name)
  }
  if (Object.keys(parameters).some(p => !Object.hasOwn(specs, p)))
    throw new Error('Unexpected parameter')
  const updated = copy(state)
  const value = action.from_param ? parameters[action.from_param] : action.value
  const observation = change(updated, action.operation, action.path, value, parameters)
  const events: PlainObject[] = []
  for (const event of scenario.events ?? []) {
    if (event.at_step === nextStep) {
      const result = change(updated, event.operation, event.path, event.value, {})
      events.push({ at_step: nextStep, operation: event.operation, path: event.path, result })
    }
  }
  return { state: updated, observation, events }
}
export function grade(state: PlainObject, scenario: ScenarioDefinition) {
  const checks = scenario.checks.map(check => {
    let actual: unknown
    try {
      const { parent, key } = location(state, pathSegments(check.path, {}))
      actual = parent[key]
    } catch { actual = undefined }
    return { name: check.name, passed: JSON.stringify(actual) === JSON.stringify(check.equals) }
  })
  const passed = checks.every(check => check.passed)
  return { passed, score: checks.filter(check => check.passed).length / checks.length, checks }
}
