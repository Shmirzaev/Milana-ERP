"""The local launcher must wire both PostgreSQL fixture mechanisms safely."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import run_local_postgres_tests as runner


def test_remote_daemon_refused_before_starting_resources(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote:2375")
    with patch.object(runner, "docker", return_value=json.dumps("unix:///local.sock")) as docker:
        with pytest.raises(RuntimeError, match="local Unix-socket"):
            runner.main()
    assert docker.call_count == 1


def test_launcher_supplies_legacy_and_approved_identity_without_publishing_database(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    identity = {"server_version": "17.7", "system_identifier": "123456", "data_directory": "/var/lib/postgresql/data"}
    docker_calls = []
    commands = []

    def docker(*args):
        docker_calls.append(args)
        if args[:2] == ("context", "inspect"):
            return json.dumps("unix:///local.sock")
        if "psql" in args:
            return json.dumps(identity)
        return ""

    def run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0)

    with patch.object(runner, "docker", side_effect=docker), patch.object(runner.subprocess, "run", side_effect=run):
        assert runner.main() == 0
    launch = next(args for args in commands if args[:2] == ["docker", "run"])
    env = dict(launch[index + 1].split("=", 1) for index, arg in enumerate(launch) if arg == "-e")
    assert env["STABILIZATION_POSTGRES_URL"] == "postgresql+psycopg2://postgres@127.0.0.1:55432/milana_test"
    assert env["S06_POSTGRES_URL"] == env["STABILIZATION_POSTGRES_URL"]
    assert env["FN04_TEST_PG_ADMIN_URL"] == "postgresql+psycopg2://postgres@127.0.0.1:55432/postgres"
    assert env["MILANA_REQUIRE_TEST_PG"] == "1"
    approved = json.loads(env["MILANA_TEST_PG_INSTANCE"])
    assert approved == {**identity, "admin_dsn": env["FN04_TEST_PG_ADMIN_URL"],
                        "host": "127.0.0.1", "port": 55432, "target_prefix": "review_ci_refactor_"}
    assert env["SALES_LIST_REVIEW_URL"].endswith("/review_sales_list_local")
    assert env["FORECAST_CREATE_REVIEW_URL"].endswith("/review_forecast_local")
    assert "--network" in launch and launch[launch.index("--network") + 1].startswith("container:milana-postgres-tests-")
    assert not any(arg in {"-p", "--publish"} for args in docker_calls if args[0] == "run" for arg in args[:args.index("postgres:17-alpine")])
    assert any(args[:3] == ["docker", "rm", "-f"] for args in commands)


def test_internal_mode_refuses_host_execution(monkeypatch):
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--inside"])
    with patch.object(runner.Path, "is_file", return_value=False):
        with pytest.raises(RuntimeError, match="disposable container"):
            runner.main()


def test_failed_container_creation_does_not_remove_unowned_resources(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    with patch.object(runner, "docker", side_effect=[json.dumps("unix:///local.sock"), RuntimeError("name occupied")]), patch.object(runner.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="name occupied"):
            runner.main()
    run.assert_not_called()


@pytest.mark.parametrize("bad_tag", ["failure", "skipped"])
def test_default_collection_including_s06_is_not_run_twice_and_bad_report_fails(tmp_path, monkeypatch, capsys, bad_tag):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        report = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--junitxml="))
        runner.ET.ElementTree(runner.ET.fromstring(
            f'<testsuite><testcase classname="backend.tests.test_stock_adjustment_postgres" name="race"><{bad_tag}/></testcase></testsuite>'
        )).write(report)
        return SimpleNamespace(returncode=0)

    with patch.object(runner.subprocess, "run", side_effect=run), patch.object(runner, "check_report", return_value={}), patch.object(runner, "expected_nodeids", return_value=[]), patch.object(runner, "check_supplement", return_value={"case_count": 0}):
        assert runner.run_tests() == 1
    assert len(commands) == 1
    assert f'"{"failed" if bad_tag == "failure" else "skipped"}": 1' in capsys.readouterr().out
