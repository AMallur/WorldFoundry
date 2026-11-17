"""An installable user-owned environment module; no WorldFoundry source edits."""
from worldfoundry import ActionSpec, ValidationCheck, ValidationResult, WorldFoundry


class CounterEnvironment:
    id = "counting"
    name = "Counter"
    description = "Example of a custom stateful environment"
    tasks = ("target",)
    instruction = "Reach the exact target."

    def __init__(self, settings):
        self.target = settings.get("target", 5)

    def initial_state(self, seed):
        return {"count": seed % 3, "target": self.target}

    def actions(self):
        return (
            ActionSpec("inspect", "Read state", {}),
            ActionSpec("add", "Increase counter", {
                "amount": {"type": "number"}
            }, ("amount",)),
        )

    def perform(self, state, action, parameters):
        if action == "inspect":
            return dict(state)
        if action == "add":
            state["count"] += parameters["amount"]
            return dict(state)
        raise ValueError("Unknown action")

    def validate(self, state):
        passed = state["count"] == state["target"]
        return ValidationResult(
            passed, float(passed),
            (ValidationCheck("reached_target", passed, "Exact target reached"),),
        )


def register(wf):
    wf.environments.register_template("counting", CounterEnvironment)


def main():
    wf = WorldFoundry.local(".wf-custom", plugins=["examples.custom_counter_template"])
    env = wf.environments.create(template="counting", config={"target": 11})

    def agent(instruction, tools):
        observed = tools.inspect()
        tools.add(amount=observed["target"] - observed["count"])
        tools.submit()

    registered = wf.agents.register(name="counter-agent", handler=agent)
    result = wf.training.create(agent=registered, environment=env, episodes=10, seed=3)
    print(result.summary)


if __name__ == "__main__":
    main()
