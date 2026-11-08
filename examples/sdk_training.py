"""Run a batch of simulated support desk episodes using the local SDK."""
from worldfoundry import WorldFoundry


def support_agent(task, tools):
    print(task)
    tools.get_ticket(ticket_id="TCK-100")
    tools.set_priority(ticket_id="TCK-100", priority="critical")
    tools.assign(ticket_id="TCK-100", assignee="on-call")
    tools.reply(ticket_id="TCK-100", message="We acknowledge the outage and opened an incident.")
    tools.resolve(ticket_id="TCK-100")
    tools.submit()


wf = WorldFoundry.local(".wf-example")
environment = wf.environments.create(template="customer_support")
agent = wf.agents.register(name="support_agent", handler=support_agent)
run = wf.training.create(agent=agent, environment=environment, episodes=3)
print(run.summary)
print(run.report_path)
