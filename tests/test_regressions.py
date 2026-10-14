from source_checks import read_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_uses_atomic_current_and_traversable_opt_path():
    s = read_source(ROOT / "install.sh")
    assert "install -d -m 755 /opt/aster /opt/aster/releases" in s
    assert 'atomic_current "$release"' in s
    assert 'ln -sfn "$release" /opt/aster/current' not in s
    assert "previous=$(readlink -f /opt/aster/current" in s
    assert '[[ "$previous" == /opt/aster/releases/*' in s


def test_browser_runtime_is_separate_from_code_runtime():
    install = read_source(ROOT / "install.sh")
    broker = read_source(ROOT / "app/broker.py")
    assert "runtimes['runsc-browser']" in install
    assert "'runtimeArgs':['--network=host']" in install
    assert "runtime='runsc-browser' if kind=='browser' else 'runsc'" in broker
    assert "network='aster-sandbox' if kind=='browser' else 'aster-code'" in broker


def test_broker_no_longer_requires_published_container_port():
    s = read_source(ROOT / "app/broker.py")
    assert "get('IPAddress')" in s
    assert "['Ports']['8001/tcp'][0]['HostPort']" not in s
    assert "'-p','127.0.0.1::8001'" not in s


def test_chat_backend_is_direct_search_only_and_worker_excludes_chat():
    core_py = read_source(ROOT / "app/core.py")
    chat_py = read_source(ROOT / "app/chat.py")
    main = read_source(ROOT / "app/main.py")
    assert "mode='work' AND status IN ('queued','running')" in core_py
    assert "'name':'search_web'" in chat_py and "CHAT_TOOLS" in chat_py
    assert "browser" not in chat_py.split("CHAT_TOOLS=", 1)[1].split("]", 1)[0]
    assert (
        "initial=bool(b.get('initial',False))" in main
        and "await chat_turn(r,text=None if initial else content,initial=initial,"
        in main
    )
    assert (
        "Chat mode does not use browser, files, code sandboxes, or computer tools"
        in main
    )


def test_sandbox_capacity_queues_or_evicts_instead_of_429_busy_error():
    broker = read_source(ROOT / "app/broker.py")
    assert "All sandbox slots are busy" not in broker
    assert "victim_key" in broker and "await retire(victim)" in broker
    assert "inuse=set()" in broker
    assert "operation in ('stop','release','stop-browser','stop-code')" in broker


def test_broker_caches_container_endpoint_for_fast_frame_streaming():
    broker = read_source(ROOT / "app/broker.py")
    assert "urls={}" in broker
    assert "if n in urls:return urls[n]" in broker
    assert "@app.get('/task/{task}/frame.jpg')" in broker


def test_completed_work_releases_checkpointed_code_capacity_and_chat_never_brokers():
    worker = read_source(ROOT / "app/worker.py")
    chat = read_source(ROOT / "app/chat.py")
    assert worker.count("await broker(task,'release')") >= 1
    assert "broker(" not in chat


def test_installer_checks_capabilities_before_any_reset():
    s = read_source(ROOT / "install.sh")
    assert s.index('scripts/linux_host.py') < s.index('scripts/reset_installation.py')
    assert '--prepared-host' in s
    assert '--check-system' in s


def test_host_unit_test_does_not_require_legacy_python_alias_and_installer_validates_container_python():
    sandbox_test = read_source(ROOT / "tests/test_sandbox.py")
    install = read_source(ROOT / "install.sh")
    assert "python3 -c 'print(2+2)'" in sandbox_test
    assert "python -c 'print(2+2)'" not in sandbox_test
    assert (
        "docker run --rm --runtime=runsc --network=none --entrypoint python aster-sandbox:3"
        in install
    )
    assert "CODE_SANDBOX_PYTHON_OK" in install


def test_browser_supports_forward_reload_and_human_endpoint_allows_them():
    tools_py = read_source(ROOT / "app/tools.py")
    sandbox = read_source(ROOT / "sandbox/server.py")
    main = read_source(ROOT / "app/main.py")
    assert "'forward','reload'" in tools_py
    assert "elif kind=='forward'" in sandbox and "elif kind=='reload'" in sandbox
    assert "'back','forward','reload'" in main


def test_retained_per_message_sources_settings_titles_and_fixed_models():
    main = read_source(ROOT / "app/main.py")
    chat = read_source(ROOT / "app/chat.py")
    core = read_source(ROOT / "app/core.py")
    providers = read_source(ROOT / "app/providers.py")
    install = read_source(ROOT / "install.sh")
    tools = read_source(ROOT / "app/tools.py")
    worker = read_source(ROOT / "app/worker.py")
    assert "message['sources']=[dict(x) for x in s.get('sources',[])]" in chat
    assert "if isinstance(m.get('sources'),list):item['sources']" in main
    assert "model_call_stream" in providers and "'chat_delta'" in chat
    assert "@app.delete('/api/tasks/{id}')" in main
    assert "CREATE TABLE IF NOT EXISTS preferences" in core
    assert "@app.get('/api/settings')" in main and "@app.put('/api/settings')" in main
    assert "@app.post('/api/change-password')" in main
    assert (
        "generate_title" in providers and "core.event(task_id,'title_updated'" in main
    )
    assert "CHAT_MODEL_DEFAULT='google/gemini-3.5-flash-lite'" in providers
    assert "WORK_MODEL_DEFAULT='openai/gpt-5.6-luna'" in providers
    assert "body={'model':selected" in providers and "body['models']" not in providers
    assert "switch_model" not in tools
    assert "('ASTER_CHAT_MODEL','google/gemini-3.5-flash-lite')" in install
    assert "('ASTER_WORK_MODEL','openai/gpt-5.6-luna')" in install
    assert "mode='work' AND status IN ('queued','running')" in core
    assert "mode='work' AND status IN ('queued','running')" in read_source(
        Path("app/scheduling.py")
    )
    assert "turn_completed" in worker and "'call_id':key" in worker
    assert "asyncio.create_task(_initial_chat" not in main


def test_browser_still_uses_finite_jpeg_frames():
    main = read_source(ROOT / "app/main.py")
    sandbox = read_source(ROOT / "sandbox/server.py")
    assert "@app.get('/api/tasks/{id}/browser-frame')" in main
    assert "multipart/x-mixed-replace" not in main
    assert "@app.get('/frame.jpg')" in sandbox
    assert "X-Aster-Frame-Seq" in main and "X-Aster-Frame-Seq" in sandbox
