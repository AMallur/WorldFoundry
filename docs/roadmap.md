# Product and distribution roadmap

## Already implemented in this repository

- Installable local Python project with SDK and two CLI entry points.
- Persistent stateful episodes and deterministic validators.
- JSONL traces and exports.
- Local HTTP API and end-to-end examples.
- Framework-neutral Google ADK tool adapter.
- Automated tests.

## Release gates

### PyPI and `uvx`

1. Confirm and reserve the `worldfoundry` distribution name through the package owner's PyPI account.
2. Add trusted publishing from tagged releases.
3. Build wheel and source distribution, inspect their contents, and test each in clean Python
   3.11–3.13 environments.
4. Publish to TestPyPI, run the documented install flow, then publish to PyPI.
5. Only after that change the README from future commands to verified public commands.

### Homebrew

1. Create a tap owned by the company.
2. Generate a formula from the signed PyPI source artifact and its SHA-256 checksum.
3. Test on current Intel and Apple Silicon macOS runners.
4. Add release automation and a rollback procedure.

### Hosted SaaS

1. Freeze and version the REST contract.
2. Add workspaces, API keys, tenant authorization, quotas, metering, and audit logs.
3. Run each episode in a time- and resource-bounded isolated worker.
4. Require client-generated idempotency keys on action calls and reject conflicting replays.
5. Store traces immutably and keep mutable query indexes separate.
6. Add environment bundles with manifests, versioning, signatures, and compatibility checks.
7. Add hosted SDK transport while keeping the local transport for tests and offline development.

### Training and evaluation platform

1. Batch episode creation with dataset row identifiers and controlled seeds.
2. Eval-suite manifests, baselines, regression thresholds, and run comparison.
3. Human review queues and feedback exports.
4. Integrations for agent frameworks, CI systems, and experiment trackers.

Actual RL, fine-tuning, reward-model training, and weight updates remain separate systems. A future
WorldFoundry service may export trajectories and scores to those systems without claiming to be
the optimizer itself.

