import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  validateEnvironment, validateScenario, applyAction, grade,
} from '../supabase/functions/worldfoundry-customer-api/runtime.ts';

const env = validateEnvironment({
  instruction: 'Resolve the order without breaking policy.',
  initial_state: {
    orders: { 'ORDER-1': { status: 'pending', notes: [], attempts: 0 } },
  },
  actions: {
    read_order: {
      operation: 'read', path: 'orders.$order_id',
      parameters: { order_id: { type: 'string' } },
    },
    resolve_order: {
      operation: 'set', path: 'orders.$order_id.status', value: 'resolved',
      parameters: { order_id: { type: 'string' } },
    },
    add_note: {
      operation: 'append', path: 'orders.$order_id.notes', from_param: 'note',
      parameters: { order_id: { type: 'string' }, note: { type: 'string' } },
    },
    retry: {
      operation: 'increment', path: 'orders.$order_id.attempts', value: 1,
      parameters: { order_id: { type: 'string' } },
    },
  },
});
const scenario = validateScenario({
  checks: [
    { name: 'resolved', path: 'orders.ORDER-1.status', equals: 'resolved' },
    { name: 'notes', path: 'orders.ORDER-1.notes', equals: ['reviewed'] },
  ],
  events: [
    { at_step: 2, operation: 'increment', path: 'orders.ORDER-1.attempts', value: 1 },
  ],
});

test('actions produce new state, event triggers and deterministic grading', () => {
  const start = structuredClone(env.initial_state);
  const params = { order_id: 'ORDER-1' };
  const first = applyAction(start, env, scenario, 'resolve_order', params, 1);
  assert.equal(first.state.orders['ORDER-1'].status, 'resolved');
  assert.equal(start.orders['ORDER-1'].status, 'pending');
  const second = applyAction(first.state, env, scenario, 'add_note',
    { ...params, note: 'reviewed' }, 2);
  assert.equal(second.events.length, 1);
  assert.equal(second.state.orders['ORDER-1'].attempts, 1);
  assert.equal(grade(second.state, scenario).score, 1);
  assert.equal(grade(start, scenario).score, 0);
});

test('unknown paths, extra parameters and dangerous keys are rejected', () => {
  assert.throws(() => applyAction(env.initial_state, env, scenario,
    'resolve_order', { order_id: '__proto__' }, 1), /Unsafe/);
  assert.throws(() => applyAction(env.initial_state, env, scenario,
    'resolve_order', { order_id: 'MISSING' }, 1), /Unknown state path/);
  assert.throws(() => applyAction(env.initial_state, env, scenario,
    'resolve_order', { order_id: 'ORDER-1', unexpected: 1 }, 1), /Unexpected/);
  assert.throws(() => validateEnvironment({
    initial_state: {}, actions: { unsafe: { operation: 'set', path: '__proto__.foo' } },
  }), /Invalid action/);
  assert.throws(() => validateScenario({
    checks: [{ name: 'bad', path: '$other', equals: 5 }],
  }), /Invalid scenario check/);
});

test('invalid oversized definitions and mutations are rejected', () => {
  assert.throws(() => validateEnvironment({
    initial_state: { blob: 'a'.repeat(70000) },
    actions: { read: { operation: 'read', path: 'blob' } },
  }), /Invalid environment/);
  const envWithLargeString = validateEnvironment({
    initial_state: { blob: '' },
    actions: { set_blob: { operation: 'set', path: 'blob', from_param: 'value',
      parameters: { value: { type: 'string' } } } },
  });
  assert.throws(() => applyAction(envWithLargeString.initial_state, envWithLargeString,
    scenario, 'set_blob', { value: 'b'.repeat(70000) }, 1), /exceeds/);
});
