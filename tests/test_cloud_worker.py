import uuid

from backend.workers.execute import execute_run

PROJECT = str(uuid.uuid4())
ENV = str(uuid.uuid4())
SCENARIO = str(uuid.uuid4())
AGENT = str(uuid.uuid4())
RUN = str(uuid.uuid4())


class Store:
    def __init__(self):
        self.records = {
            "wf_managed_runs": [{"id": RUN, "project_id": PROJECT, "executor": "cloud_tasks",
                                 "status": "queued", "requested_episodes": 2,
                                 "environment_id": ENV, "scenario_id": SCENARIO,
                                 "agent_id": AGENT, "max_steps": 5, "seed": 7,
                                 "attempt_count": 0}],
            "wf_resources": [
                {"id": ENV, "project_id": PROJECT, "kind": "environment", "config": {
                    "initial_state": {"case": {"status": "open"}},
                    "actions": {"close": {"operation": "set", "path": "case.status",
                                          "value": "closed"}},
                }},
                {"id": SCENARIO, "project_id": PROJECT, "kind": "scenario", "config": {
                    "checks": [{"name": "done", "path": "case.status", "equals": "closed"}],
                }},
                {"id": AGENT, "project_id": PROJECT, "kind": "agent", "config": {
                    "plan": [{"action": "close"}],
                }},
            ],
            "wf_managed_episodes": [], "wf_artifacts": [], "wf_managed_usage": [],
        }
        self.objects = {}

    def select(self, table, *, filters=None, limit=None, **kwargs):
        result = [row for row in self.records[table]
                  if all(row.get(k) == value.removeprefix("eq.")
                         for k, value in (filters or {}).items())]
        return result[:limit] if limit else result

    def update(self, table, values, filters):
        rows = self.select(table, filters=filters)
        for row in rows:
            row.update(values)
        return rows

    def insert(self, table, values):
        row = dict(values)
        self.records[table].append(row)
        return row

    def upload(self, bucket, key, content, media_type):
        assert bucket == "wf-artifacts"
        self.objects[key] = content


def test_worker_records_metered_episodes_and_is_idempotent():
    store = Store()
    result = execute_run(store, RUN)
    assert result["status"] == "completed"
    assert result["score_mean"] == 1
    assert len(store.records["wf_managed_episodes"]) == 2
    assert len(store.records["wf_managed_usage"]) == 1
    assert len(store.objects) == 2
    assert execute_run(store, RUN)["duplicate"]
