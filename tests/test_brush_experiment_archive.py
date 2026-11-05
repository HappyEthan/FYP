"""Success-only archival, naming, and reproduction without original input folders."""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from brushbot.experiments.archive import ExperimentArchive, PLAN_FILES, read_json, validate_name, write_json
from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
from brushbot.experiments.reproduce import archive_path, open_bundle, read_json as read_data_json, summarize, verify
from brushbot.target_strokeplan import StrokePlan
from scripts import run_strokeplan_experiment as runner
from scripts.brush_path_editor_model import PathModel
from tests.test_strokeplan_experiment import inputs


def fake_execute(args, *, plan, table, setup, artifacts, label, feedback_profile, entry_profile, work_root):
    clock = FakeClock()
    compiled = runner.compile_recorded_plan(plan, table, setup, label=label,
        control_mode=args.control_mode, feedback_profile=feedback_profile, entry_profile=entry_profile)
    arm = FakeArm(tuple(compiled['pose_m_rad'][0]), clock=clock)
    arm.realtime_state_reads = False
    class BatchSource(FakeMagneticSource):
        def read_frames(self):
            frame = super().read_frames()[0]
            return [dict(frame, sensor_t_us=frame['sensor_t_us']-16000+i*4000) for i in range(5)]
    source = BatchSource(arm, clock, contact_z_mm=setup['contact_z_mm'])
    engine, hub = runner.build_stack(plan=plan, table=table, setup=setup, artifacts=artifacts,
        label=label, root=work_root, arm=arm, source=source, clock=clock,
        control_mode=args.control_mode, feedback_profile=feedback_profile, entry_profile=entry_profile)
    result = runner.run_recorded(engine, hub, clock=clock, sleep=lambda _: time.sleep(.001))
    assert result['state'] == 'END_WAIT', result['last_error']
    return result


@pytest.fixture(scope='module')
def raw_template(tmp_path_factory):
    parent = tmp_path_factory.mktemp('raw_archive')
    plan, table, setup, artifacts = inputs(parent)
    result = fake_execute(SimpleNamespace(control_mode='feedforward'), plan=plan, table=table,
        setup=setup, artifacts=artifacts, label='fixture', feedback_profile=None,
        entry_profile=None, work_root=parent/'raw')
    return Path(result['run_dir'])


def publish(store, raw_template):
    with store.session() as stage:
        raw = stage/'raw'
        shutil.copytree(raw_template, raw)
        return store.archive_success(stage, raw)


def test_numbering_survives_restart_rename_and_cancellation(tmp_path, raw_template):
    store = ExperimentArchive(tmp_path/'records')
    first = publish(store, raw_template)
    assert first.name == '毛笔试写_001'
    first = store.rename(first, '横画磁目标150', remember=True)
    assert first.name == '横画磁目标150_001'
    run_id = read_data_json(first, 'experiment.json')['id']
    # Failed/cancelled attempts reserve no successful sequence number.
    with pytest.raises(RuntimeError):
        with store.session() as stage:
            (stage/'partial.csv').write_text('unfinished')
            raise RuntimeError('operator_stop')
    second = publish(ExperimentArchive(store.root), raw_template)
    assert second.name == '横画磁目标150_002'
    first = store.rename(first, '倾角12度')
    assert read_data_json(first, 'experiment.json')['id'] == run_id
    assert store.last_name() == '横画磁目标150'
    assert verify(first) > 10
    assert [p.name for p in first.iterdir()] == [first.name + '.brushrun']
    assert read_data_json(first, 'experiment.json')['name'] == first.name
    third = publish(store, raw_template)
    assert third.name == '横画磁目标150_003'
    assert len(store.records()) == 3
    assert not list(store.temporary.iterdir())


@pytest.mark.parametrize('name', ['', '../outside', 'x/y', 'x\\y', '.hidden', '..', 'a\nname', 'x'*181])
def test_names_cannot_escape_the_archive(name):
    with pytest.raises(ValueError):
        validate_name(name)


def test_moved_archive_can_verify_and_reproduce_with_isolated_python(tmp_path, raw_template):
    store = ExperimentArchive(tmp_path/'records')
    folder = publish(store, raw_template)
    expected = read_data_json(folder, 'analysis_summary.json')
    files = list(folder.iterdir())
    assert len(files) == 1 and files[0].name == folder.name + '.brushrun'
    with zipfile.ZipFile(files[0]) as archive:
        assert 'editor_state.json' not in archive.namelist()  # This fixture is not an editor run.
        assert 'reproduction_source.zip' not in archive.namelist()
        assert not any(n.endswith('.py') for n in archive.namelist())
    relocated = tmp_path/'only_this_file.brushrun'
    shutil.copyfile(files[0], relocated)
    shutil.rmtree(store.root)
    assert summarize(relocated) == expected
    reproduce = Path(__file__).resolve().parents[1]/'src/brushbot/experiments/reproduce.py'
    result = subprocess.run([sys.executable, '-I', str(reproduce), str(relocated)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '校验通过' in result.stdout
    with zipfile.ZipFile(relocated) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents['control.jsonl'] = b'corrupted'
    with zipfile.ZipFile(relocated, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match='control.jsonl'):
        verify(relocated)


@pytest.mark.parametrize('status', ['aborted', 'fault', 'running'])
def test_non_success_manifest_is_never_published(tmp_path, raw_template, status):
    store = ExperimentArchive(tmp_path/'records')
    with pytest.raises(ValueError, match='未成功完成'):
        with store.session() as stage:
            shutil.copytree(raw_template, stage/'raw')
            manifest = read_json(stage/'raw/manifest.json')
            manifest['status'] = status
            write_json(stage/'raw/manifest.json', manifest)
            store.archive_success(stage, stage/'raw')
    assert store.records() == []
    assert store.preview_name() == '毛笔试写_001'
    assert not list(store.temporary.iterdir())


def test_bad_tcp_and_write_errors_leave_no_saved_run(tmp_path, raw_template):
    store = ExperimentArchive(tmp_path/'records')
    with pytest.raises(ValueError, match='TCP'):
        with store.session() as stage:
            raw = stage/'raw'
            shutil.copytree(raw_template, raw)
            write_json(raw/'actual_tcp_meta.json', dict(worker_stopped=True, worker_error=None,
                valid_samples=100, invalid_samples=1))
            store.archive_success(stage, raw, require_tcp=True)
    assert not store.records()
    assert not list(store.temporary.iterdir())


def test_cleanup_preserves_live_tasks_and_recovers_only_sealed_success(tmp_path, raw_template, monkeypatch):
    store = ExperimentArchive(tmp_path/'records')
    live = store.new_stage()
    stale = store.new_stage()
    write_json(stale/'.session.json', dict(pid=-1, process_token=None, kind='trial'))
    (stale/'partial.csv').write_text('unfinished')
    unknown = store.temporary/'not_ours'
    unknown.mkdir()
    (unknown/'keep').touch()
    assert store.cleanup_stale() == []
    assert live.exists() and unknown.exists() and not stale.exists()
    store.discard_stage(live)
    with monkeypatch.context() as patch:
        patch.setattr(store, '_publish', lambda *a: (_ for _ in ()).throw(OSError('disk unavailable')))
        with pytest.raises(OSError):
            with store.session() as stage:
                shutil.copytree(raw_template, stage/'raw')
                store.archive_success(stage, stage/'raw')
        assert (stage/'payload/bundle_manifest.json').exists()
    write_json(stage/'.session.json', dict(pid=-1, process_token=None, kind='trial'))
    recovered = store.cleanup_stale()
    assert len(recovered) == 1 and verify(recovered[0]) > 10
    assert not stage.exists()
    assert (unknown/'keep').exists()


def portable_model(tmp_path):
    original = PathModel()
    source = tmp_path/'original_inputs'
    source.mkdir()
    write_json(source/'recipe.json', original.base)
    for name, value in original.settings().items():
        write_json(source/name, value)
    model = PathModel(source)
    model.use_endpoint_speeds()
    model.segment_magnetic[3] = 150.
    model.node_angles[3] = [12., -45.]
    model.node_speeds[3:5] = 2.
    first = model.stroke_id
    model.add_independent_point([10., 10.])
    model.add_independent_point([20., 10.])
    model.segment_magnetic[0] = 140.
    model.node_angles[:] = [12., -45.]
    model.switch_stroke(first)
    model.set_test_range(2, 6)
    custom = tmp_path/'selected_feedforward.json'
    write_json(custom, original.settings()['feedforward.json'])
    model.feedforward_override = str(custom)
    return model, source, custom


def test_full_editor_bundle_recompiles_identically_after_all_sources_removed(tmp_path, monkeypatch):
    model, source, custom = portable_model(tmp_path)
    folder, _ = model.export(tmp_path/'exports')
    files = {p.name: p.read_bytes() for p in folder.iterdir() if p.name in PLAN_FILES}
    before = model.state()
    expected = model.compile_workspace()[2]
    plan = StrokePlan.load(io.BytesIO(files['strokeplan.npz']))
    store = ExperimentArchive(tmp_path/'records')
    with store.session() as stage:
        result = fake_execute(SimpleNamespace(control_mode='pi'), plan=plan,
            table=json.loads(files['feedforward.json']), setup=json.loads(files['settings.json']),
            artifacts=files, label='portable', feedback_profile=json.loads(files['pi_profile.json']),
            entry_profile=json.loads(files['entry_profile.json']), work_root=stage/'raw')
        saved = store.archive_success(stage, result['run_dir'], input_files=files, require_editor=True)
    moved = tmp_path/'copied_experiment.brushrun'
    shutil.copyfile(archive_path(saved), moved)
    shutil.rmtree(store.root)
    shutil.rmtree(tmp_path/'exports')
    shutil.rmtree(source)
    custom.unlink()
    import scripts.brush_path_editor_model as editor_model
    monkeypatch.setattr(editor_model, 'CONTEXT', tmp_path/'missing_context')
    restored = PathModel.from_state(read_data_json(moved, 'editor_state.json'))
    assert np.array_equal(restored.nodes, model.nodes)
    assert restored.segment_magnetic.tolist() == model.segment_magnetic.tolist()
    assert restored.node_angles.tolist() == model.node_angles.tolist()
    assert restored.stroke_order == model.stroke_order
    assert restored.test_node_range() == (2, 6)
    actual = restored.compile_workspace()[2]
    for key in ('t_s', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m'):
        assert np.array_equal(actual[key], expected[key], equal_nan=True), key
    assert np.array_equal(actual['phase'], expected['phase'])
    assert restored.other_strokes[0]['settings_snapshot']
    assert verify(moved) > 15


@pytest.mark.parametrize('outcome', ['success', 'abort', 'exception', 'interrupt'])
def test_cli_archives_only_complete_runs_and_cleans_others(tmp_path, raw_template, monkeypatch, outcome):
    input_dir = tmp_path/'inputs'
    input_dir.mkdir()
    for name in ('strokeplan.npz', 'feedforward.json', 'settings.json'):
        shutil.copyfile(raw_template/name, input_dir/name)
    monkeypatch.setattr(runner, 'require_execution_approval', lambda *a: None)
    original_runtime = runner.runtime_settings
    monkeypatch.setattr(runner, 'runtime_settings', lambda setup, **kw: original_runtime(setup))

    def execute(args, **kwargs):
        from brushbot.experiments.archive import _ConsoleTee
        assert not isinstance(sys.stdout, _ConsoleTee)
        assert not isinstance(sys.stderr, _ConsoleTee)
        print('EXECUTION_WITHOUT_ADDED_LOG_IO')
        raw = kwargs['work_root']/'run'
        raw.parent.mkdir(parents=True)
        shutil.copytree(raw_template, raw)
        if outcome == 'exception':
            raise RuntimeError('connection lost')
        if outcome == 'interrupt':
            raise KeyboardInterrupt
        return dict(state='END_WAIT' if outcome == 'success' else 'ABORTED', run_dir=str(raw))

    monkeypatch.setattr(runner, '_execute_hardware', execute)
    root = tmp_path/'records'
    argv = [str(input_dir/'strokeplan.npz'), '--feedforward', str(input_dir/'feedforward.json'),
            '--settings', str(input_dir/'settings.json'), '--run-root', str(root), '--execute']
    named = []
    if outcome in {'exception', 'interrupt'}:
        with pytest.raises(RuntimeError if outcome == 'exception' else KeyboardInterrupt):
            runner.main(argv, confirm_execution=lambda _: 'RUN', naming_prompt=lambda *a: named.append(a))
    else:
        assert runner.main(argv, confirm_execution=lambda _: 'RUN', naming_prompt=lambda *a: named.append(a)) == (0 if outcome == 'success' else 2)
    store = ExperimentArchive(root)
    assert len(store.records()) == (1 if outcome == 'success' else 0)
    assert len(named) == (1 if outcome == 'success' else 0)
    assert not list(store.temporary.iterdir())
    from brushbot.experiments.reproduce import read_bytes
    saved = store.records()[0]['path'] if outcome == 'success' else next(store.failures.iterdir())
    assert b'EXECUTION_WITHOUT_ADDED_LOG_IO' not in read_bytes(saved, 'console.log')
    if outcome in ('exception', 'interrupt'):
        assert read_json(saved/'failure.json')['exception']['type'] == ('RuntimeError' if outcome == 'exception' else 'KeyboardInterrupt')


def test_cli_cancel_and_preview_create_no_run_directory(tmp_path, raw_template, monkeypatch):
    root = tmp_path/'records'
    monkeypatch.setattr(runner, 'require_execution_approval', lambda *a: None)
    original_runtime = runner.runtime_settings
    monkeypatch.setattr(runner, 'runtime_settings', lambda setup, **kw: original_runtime(setup))
    argv = [str(raw_template/'strokeplan.npz'), '--feedforward', str(raw_template/'feedforward.json'),
            '--settings', str(raw_template/'settings.json'), '--run-root', str(root)]
    assert runner.main(argv) == 0
    assert runner.main(argv+['--execute'], confirm_execution=lambda _: '') == 0
    assert not root.exists()


@pytest.fixture(scope='module')
def app():
    from PyQt5 import QtWidgets
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_naming_dialog_default_cancel_and_history_rename(app, tmp_path, raw_template):
    from scripts.brush_experiment_dialogs import ExperimentNameDialog
    store = ExperimentArchive(tmp_path/'records')
    first = publish(store, raw_template)
    dialog = ExperimentNameDialog(store, first, completion=True)
    assert dialog.preview.text() == '毛笔试写_001'
    dialog.reject()
    assert first.exists()
    dialog = ExperimentNameDialog(store, first, completion=True)
    dialog.name.setText('横画磁目标150')
    assert dialog.preview.text() == '横画磁目标150_001'
    dialog.save()
    assert dialog.result() == dialog.Accepted
    assert store.last_name() == '横画磁目标150'
    history = ExperimentNameDialog(store, dialog.folder)
    history.name.setText('重新整理')
    history.save()
    assert history.folder.name == '重新整理_001'
    assert store.last_name() == '横画磁目标150'
    assert verify(history.folder) > 10


def test_record_browser_and_offline_data_window(app, tmp_path, raw_template):
    from PyQt5 import QtWidgets
    from scripts.brush_experiment_dialogs import ExperimentRecordsDialog, ExperimentDataDialog
    store = ExperimentArchive(tmp_path/'records')
    folder = publish(store, raw_template)
    calls = []
    browser = ExperimentRecordsDialog(store, calls.append)
    assert browser.table.rowCount() == 1
    browser.restore_selected()
    assert calls == [folder]
    viewer = ExperimentDataDialog(folder)
    viewer.show()
    app.processEvents()
    assert viewer.findChild(QtWidgets.QTabWidget).count() == 3
    viewer.close()
    browser.close()


def test_editor_restores_portable_settings_and_launches_only_temporary_plan(app, tmp_path, monkeypatch, raw_template):
    import scripts.edit_brush_path as ui
    model, source, custom = portable_model(tmp_path)
    model.endpoint_speed_mode = False
    model.segment_speeds[3] = 1.8
    model.speed_positions[3] = .25
    export, _ = model.export(tmp_path/'exports')
    store = ExperimentArchive(tmp_path/'records')
    with store.session() as stage:
        shutil.copytree(raw_template, stage/'raw')
        saved = store.archive_success(stage, stage/'raw',
            input_files={'editor_state.json': (export/'editor_state.json').read_bytes()}, require_editor=True)
    relocated = tmp_path/'copied_experiment.brushrun'
    shutil.copyfile(archive_path(saved), relocated)
    shutil.rmtree(saved)
    shutil.rmtree(source)
    shutil.rmtree(tmp_path/'exports')
    custom.unlink()
    monkeypatch.setattr(ui, 'ExperimentArchive', lambda: store)
    monkeypatch.setattr(ui, 'DRAFT', tmp_path/'draft.json')
    original_model = PathModel()
    original_model.nodes[:, 0] += 120.
    win = ui.Editor(original_model)
    original_handles = list(win.handles)
    original_path = win.curve.getData()[0].copy()
    original_archive = relocated.read_bytes()
    monkeypatch.setattr(ui.W.QFileDialog, 'getOpenFileName', lambda *a: (str(relocated), ''))
    win.open_experiment_file()
    assert not win.model.endpoint_speed_mode
    assert win.model.segment_speeds.tolist() == model.segment_speeds.tolist()
    assert win.model.speed_positions.tolist() == model.speed_positions.tolist()
    assert win.model.segment_magnetic.tolist() == model.segment_magnetic.tolist()
    assert win.model.node_angles.tolist() == model.node_angles.tolist()
    assert not np.array_equal(win.curve.getData()[0], original_path)
    assert all(handle not in win.handles for handle in original_handles)
    assert len(win.handles) == len(model.nodes)
    for handle, xy in zip(win.handles, model.nodes):
        assert np.array_equal([handle.pos().x(), handle.pos().y()], xy)
    for actual, expected in zip(win.curve.getData(), model.test_points().T):
        assert np.array_equal(actual, expected)
    assert len(win.other_stroke_curves) == len(model.other_strokes)
    for curve, state in zip(win.other_stroke_curves, model.other_strokes):
        for actual, expected in zip(curve.getData(), PathModel.from_state(state).points().T):
            assert np.array_equal(actual, expected)
    assert win.stroke_selector.count() == len(model.stroke_order)
    assert win.table.rowCount() == len(model.nodes)-1
    assert win.model.test_node_range() == model.test_node_range()
    assert win.isVisible()
    assert not win.experiment_viewer.isVisible()
    assert '已恢复到画板' in win.status.text()
    assert np.array_equal(PathModel.restore(ui.DRAFT).nodes, model.nodes)
    calls = []
    monkeypatch.setattr(ui.subprocess, 'run', lambda command, **kw: calls.append(command))
    win.launch_trial()
    assert len(calls) == 1 and '--consume-stage' in calls[0][-1]
    assert len(list(store.temporary.iterdir())) == 1
    stage = next(store.temporary.iterdir())
    state_path = next(stage.rglob('editor_state.json'))
    assert read_json(state_path)['settings_snapshot']
    assert not (store.root/'路径版本').exists()
    assert not win.experiment_viewer.isVisible()
    assert win.experiment_viewer.findChild(ui.W.QTabWidget).count() == 3
    verify(relocated)
    win.close()
    assert relocated.read_bytes() == original_archive
    store.discard_stage(stage)


@pytest.mark.parametrize('fails', [False, True])
def test_trial_wrapper_cleans_consumed_plan_on_exit(tmp_path, monkeypatch, fails):
    from scripts import run_edited_brush_path as wrapper
    store = ExperimentArchive(tmp_path/'records')
    stage = store.new_stage(kind='launch')
    model = PathModel()
    folder, _ = model.export(stage/'plan')
    def execute(*a, **kw):
        if fails:
            raise RuntimeError('execution failed')
        return 0
    monkeypatch.setattr(wrapper, 'run_experiment', execute)
    argv = [str(folder), '--run-root', str(store.root), '--consume-stage', str(stage)]
    if fails:
        with pytest.raises(RuntimeError):
            wrapper.main(argv)
    else:
        assert wrapper.main(argv) == 0
    assert not stage.exists()


def test_failed_rename_keeps_original_archive_and_name(tmp_path, raw_template, monkeypatch):
    import brushbot.experiments.archive as archive_module
    store = ExperimentArchive(tmp_path/'records')
    folder = publish(store, raw_template)
    original = archive_path(folder).read_bytes()
    def disk_full(*args):
        raise OSError('disk full')
    monkeypatch.setattr(archive_module, 'pack_bundle', disk_full)
    with pytest.raises(OSError, match='disk full'):
        store.rename(folder, '新名称', remember=True)
    assert archive_path(folder).read_bytes() == original
    assert store.last_name() == '毛笔试写'
    assert len(store.records()) == 1
    assert not list(store.temporary.iterdir())


@pytest.mark.parametrize('case', ['version', 'traversal', 'missing', 'duplicate'])
def test_invalid_archives_are_rejected_before_extracting(tmp_path, raw_template, case):
    store = ExperimentArchive(tmp_path/'records')
    folder = publish(store, raw_template)
    path = archive_path(folder)
    with zipfile.ZipFile(path) as archive:
        contents = {n: archive.read(n) for n in archive.namelist()}
    if case == 'version':
        manifest = json.loads(contents['bundle_manifest.json'])
        manifest['version'] = 999
        contents['bundle_manifest.json'] = json.dumps(manifest).encode()
    elif case == 'traversal':
        contents['../outside.json'] = b'{}'
    elif case == 'missing':
        contents.pop('control.jsonl')
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        if case == 'duplicate':
            with pytest.warns(UserWarning, match='Duplicate'):
                archive.writestr('control.jsonl', contents['control.jsonl'])
    with pytest.raises(ValueError):
        with open_bundle(path):
            pytest.fail('Invalid archive was extracted')
    assert not (tmp_path/'outside.json').exists()


def test_recorded_magnetic_curves_and_tcp_survive_single_file_copy(app, tmp_path, raw_template):
    import pyqtgraph as pg
    from PyQt5 import QtWidgets
    from scripts.brush_experiment_dialogs import ExperimentDataDialog
    from brushbot.experiments.reproduce import load_control
    store = ExperimentArchive(tmp_path/'records')
    with store.session() as stage:
        raw = stage/'raw'
        shutil.copytree(raw_template, raw)
        (raw/'actual_tcp.csv').write_text('valid,x_m,y_m\nTrue,0.1,0.2\nTrue,0.11,0.21\n')
        write_json(raw/'actual_tcp_meta.json', dict(worker_stopped=True, worker_error=None,
            valid_samples=2, invalid_samples=0))
        folder = store.archive_success(stage, raw, require_tcp=True)
    copied = tmp_path/'copied.brushrun'
    shutil.copyfile(archive_path(folder), copied)
    shutil.rmtree(store.root)
    control = load_control(copied)
    viewer = ExperimentDataDialog(copied)
    tabs = viewer.findChild(QtWidgets.QTabWidget)
    actual_xy = tabs.widget(0).listDataItems()[1].getData()
    assert np.allclose(actual_xy[0], [100, 110])
    assert np.allclose(actual_xy[1], [200, 210])
    curves = tabs.widget(1).listDataItems()
    for curve, key in zip(curves, ('a_ref_uT', 'a_control_uT')):
        x, y = curve.getData()
        assert np.array_equal(x, [row['t_s'] for row in control])
        expected = [np.nan if row.get(key) is None else row[key] for row in control]
        assert np.array_equal(y, expected, equal_nan=True)
    viewer.close()


def test_manual_path_exports_keep_the_original_library_location(tmp_path, monkeypatch):
    import scripts.brush_path_editor_model as module
    model = PathModel()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    folder, _ = model.export()
    assert folder.is_relative_to(tmp_path/'runs/brush2/plans/interactive')
    assert not (tmp_path/'runs/毛笔实验数据').exists()
