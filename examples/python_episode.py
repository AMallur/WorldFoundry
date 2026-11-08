from pathlib import Path

from worldfoundry import WorldFoundry


def main() -> None:
    client = WorldFoundry(Path(".wf-example"))
    episode = client.start("support-desk", seed=7)
    print(f"Episode: {episode.id}")
    print(episode.instruction)

    client.act(episode.id, "get_ticket", ticket_id="TCK-100")
    client.act(episode.id, "set_priority", ticket_id="TCK-100", priority="critical")
    client.act(episode.id, "assign", ticket_id="TCK-100", assignee="on-call")
    client.act(
        episode.id,
        "reply",
        ticket_id="TCK-100",
        message="We acknowledge the outage and have opened an incident.",
    )
    client.act(episode.id, "resolve", ticket_id="TCK-100")
    result = client.submit(episode.id)
    print(result.to_dict())
    print(f"Trace: {client.export_trace(episode.id, '.wf-example/trace.jsonl')}")


if __name__ == "__main__":
    main()

