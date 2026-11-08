import json

from worldfoundry.cli import main


def test_cli_persists_between_calls_and_exports(tmp_path, capsys):
    home = str(tmp_path / "home")
    assert main(["--home", home, "episodes", "start", "support-desk"]) == 0
    episode_id = json.loads(capsys.readouterr().out)["id"]

    params = '{"ticket_id":"TCK-100"}'
    assert main(["--home", home, "episodes", "act", episode_id, "get_ticket", "--params", params]) == 0
    assert json.loads(capsys.readouterr().out)["observation"]["ticket"]["id"] == "TCK-100"

    output = tmp_path / "trace.jsonl"
    assert main(["--home", home, "traces", "export", episode_id, "-o", str(output)]) == 0
    assert output.exists()
    assert len(output.read_text().splitlines()) == 2

