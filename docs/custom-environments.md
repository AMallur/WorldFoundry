# WorldFoundry user-owned environments (v0.6)

WorldFoundry now supports arbitrary local Python environment plugins, JSON
environment templates, parameterized scenario generators, custom agent
adapters, and read-only connector snapshots. No need to modify WorldFoundry
source to introduce a new industry/workflow.

## JSON (no Python environment class)

Import and run the included warehouse definition:

    worldfoundry --home .wf-data environments import examples/warehouse.environment.json

Use the returned environment ID in:

    worldfoundry --home .wf-data episodes start ENVIRONMENT_ID --seed 9
    worldfoundry --home .wf-data episodes act EPISODE_ID inspect
    worldfoundry --home .wf-data episodes act EPISODE_ID verify
    worldfoundry --home .wf-data episodes act EPISODE_ID ship
    worldfoundry --home .wf-data episodes act EPISODE_ID note --params '{"message":"checked"}'
    worldfoundry --home .wf-data episodes submit EPISODE_ID

JSON templates configure state, named actions, argument schemas, read/set/
append/increment operations, grader checks, instructions and seeded variants.
They never execute arbitrary external code.

## Python plugin (arbitrary local simulation behavior)

See examples/custom_counter_template.py. Implement:
- id, name, description, tasks, instruction
- initial_state(seed) returning a JSON-serializable dictionary
- actions() returning ActionSpec objects
- perform(state, action, parameters) returning an observation dictionary
- validate(state) returning ValidationResult

Export a register(wf) function that calls:

    wf.environments.register_template("counting", CounterEnvironment)

Local Python programs load it using:

    wf = WorldFoundry.local(".wf-data", plugins=["examples.custom_counter_template"])

The CLI and local REST server can use the same module:

    worldfoundry --plugin examples.custom_counter_template environments list
    worldfoundry --plugin examples.custom_counter_template serve

The module must be importable in the Python environment. Re-register the
plugin each time you start a new process; episode state and template settings
are persisted, but developer Python functions are not serialized. Import
only local modules that you trust.

## Custom scenarios and conditional agents

    wf.scenarios.register_generator("exceptions", lambda seed, cfg: {
        "instruction": "Resolve exception " + str(seed),
        "state_overrides": {"orders": {"ORD1": {"status": "held"}}},
        "events": [
            {"at_step": 1, "operation": "set",
             "path": "orders.ORD1.status", "value": "delayed"}
        ],
        "checks": [
            {"name": "shipped", "path": "orders.ORD1.status",
             "equals": "shipped"}
        ],
    })
    scenario = wf.scenarios.create(name="Order exceptions", generator="exceptions")
    run = wf.training.create(agent=registered_agent, environment=env,
                             scenario=scenario, episodes=100, seed=42)

To connect a developer's existing agent, register a Python callable taking
(instruction, tools), or an object with run(instruction, tools). The available
tools are obtained from that environment rather than the support-desk list.

## Authorized third-party sources

A connector implements snapshot() -> dict. Register it in Python:

    wf.connectors.register("orders", my_authorized_connector)

Then create a snapshot template with config containing:
- connector: "orders"
- mount: "orders"
- initial_state: {"orders": {}}
- actions: declarative tool schema using orders.<field> paths
- checks: expected simulated outcomes

WorldFoundry calls snapshot() once per episode. Every action after that
modifies only the local episode state, never external production systems.
Network credentials belong inside the developer-owned connector object,
not in the WorldFoundry JSON configuration or public SDK.

## Limitations

The open-ended Python plugin and connector pathway currently runs locally.
Hosted Supabase accepts declarative JSON with a more restrictive interpreter.
Arbitrary Python plugin code is not uploaded or executed on shared cloud
workers. Local concurrency remains sequential. Training runs generate
trajectories and grades but do not update model weights.
