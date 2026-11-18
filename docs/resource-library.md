# WorldFoundry customer resource library (v0.7.0)

WorldFoundry stores customer-authored templates, environments, scenarios, agents, workflows, tools, applications, datasets, policies and validators in the WorldFoundry-owned Supabase project. The Python SDK connects exclusively to the authenticated WorldFoundry HTTPS API; never put Supabase administrative credentials in customer code.

## Create templates and environments

    import os
    from worldfoundry import WorldFoundry

    wf = WorldFoundry.cloud(api_key=os.environ["WORLDFOUNDRY_API_KEY"])
    project = wf.projects.create(name="Operations lab")
    pid = project["id"]
    template = wf.templates.create(
        project_id=pid, name="Warehouse",
        config={
            "initial_state": {"order": {"status": "pending"}},
            "actions": {
                "ship": {"operation": "set", "path": "order.status",
                         "value": "shipped"}
            }
        }
    )
    env = wf.environments.from_template(
        project_id=pid, name="Warehouse A", template_id=template["id"],
        overrides={"initial_state": {"order": {"status": "held"}}}
    )
    scenario = wf.scenarios.create(
        project_id=pid, name="Ship order",
        config={"checks": [{"name": "shipped",
                            "path": "order.status", "equals": "shipped"}]}
    )

A template is copied when creating an environment. Later changes to the template do not alter existing environments. The source template ID and version are recorded in the environment configuration.

## Retrieve as many resources as you need

    for environment in wf.environments.iter_all(pid):
        print(environment["id"], environment["name"], environment["version"])

Or request a single page:

    page = wf.environments.list(pid, limit=50, offset=0)
    more = page["next_offset"]

Each resource has a stable UUID. Use GET for a specific ID, list with a project filter, or iterate across pages. There is no fixed count of environments or templates per project; physical database capacity, per-record sizes, quotas and billing still apply.

## Edit, archive, and restore safely

    current = wf.environments.get(env["id"])
    edited = wf.environments.configure(
        env["id"], expected_version=current["version"],
        config={**current["config"], "instruction": "Verify then ship"}
    )
    history = wf.environments.versions(env["id"])
    old = wf.environments.version(env["id"], 1)
    archived = wf.environments.archive(
        env["id"], expected_version=edited["version"]
    )
    restored = wf.environments.restore(
        env["id"], version=1, expected_version=archived["version"]
    )

A successful update creates a new version. Conflicting versions return HTTP 409 instead of losing another user's changes. Archiving hides resources from ordinary lists without erasing history. Restoring creates a new version.

## Storage and access guarantees

- Database tables wf_resources and wf_resource_revisions persist definitions and immutable revisions.
- WorldFoundry checks customer API key scopes and project ownership before accessing a resource; the service credential remains on the server.
- Resource definitions have a 128 KiB limit each. Use the private WorldFoundry artifact API for larger datasets and traces.
- Hosted simulation sessions snapshot their exact environment and scenario configuration when created; later edits cannot change a session's rules.
- Do not put OAuth refresh tokens, passwords, Supabase credentials or API secrets inside a resource config. Credentials for third-party connectors belong in a separate future secure credential service.
- This metadata and execution-state storage works without a customer-controlled Supabase project or cloud-compute worker. Arbitrary Python plugins remain local only.
