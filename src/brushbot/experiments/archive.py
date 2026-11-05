"""Successful experiment archives and retained unsuccessful session data."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
import fcntl
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import traceback
import uuid
import zipfile
from zoneinfo import ZoneInfo

from .reproduce import archive_path, file_hash, open_bundle, read_json as read_data_json, summarize, verify

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / 'runs' / '毛笔实验数据'
PLAN_FILES = ('strokeplan.npz', 'feedforward.json', 'settings.json', 'entry_profile.json',
              'pi_profile.json', 'recipe.json', 'workspace_recipe.json', 'editor_state.json',
              'preflight.json', 'segment_target_audit.json', 'speed_adaptation.json',
              'writing_variation.json')


class _ConsoleTee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log

    def write(self, text):
        self.log.write(text)
        return self.terminal.write(text)

    def flush(self):
        self.log.flush()
        self.terminal.flush()

    def __getattr__(self, name):
        return getattr(self.terminal, name)


def terminal_stream(stream):
    """Resolve the original terminal, including nested archive log wrappers."""
    while isinstance(stream, _ConsoleTee):
        stream = stream.terminal
    return stream


@contextmanager
def without_console_capture():
    """Keep added archive log I/O outside hardware execution and live output."""
    with redirect_stdout(terminal_stream(sys.stdout)), redirect_stderr(terminal_stream(sys.stderr)):
        yield


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('请填写实验名称')
    name = name.strip()
    if (name in {'.', '..'} or name.startswith('.') or name.endswith('.')
            or re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]', name)
            or len(name.encode('utf-8')) > 180):
        raise ValueError('名称不能包含路径分隔符或特殊字符，且不能超过 180 个 UTF-8 字节')
    return name


def _process_token(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (OSError, IndexError):
        return None


def environment_snapshot():
    packages = {}
    for name in ('numpy', 'PyQt5', 'pyqtgraph', 'pyserial', 'matplotlib'):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    program = hashlib.sha256()
    for directory in ('src', 'scripts'):
        for path in sorted((REPO_ROOT / directory).rglob('*.py')):
            program.update(path.relative_to(REPO_ROOT).as_posix().encode('utf-8'))
            program.update(bytes.fromhex(file_hash(path)))
    return dict(python=sys.version, platform=platform.platform(), packages=packages,
                program_sha256=program.hexdigest(), archive_format_version=1, timezone='Asia/Shanghai')


def seal_bundle(folder):
    folder = Path(folder)
    checksums = {str(path.relative_to(folder)): file_hash(path) for path in sorted(folder.rglob('*'))
                 if path.is_file() and path.name != 'bundle_manifest.json'}
    write_json(folder / 'bundle_manifest.json', dict(version=1, format='brushrun', sha256=checksums))


def pack_bundle(folder, target):
    """Write, flush and verify one portable archive; no code or path-library copies."""
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(Path(folder).rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    with Path(target).open('rb') as stream:
        os.fsync(stream.fileno())
    verify(target)


def validate_recording(folder, *, require_tcp=False):
    folder = Path(folder)
    manifest = read_json(folder / 'manifest.json')
    if manifest.get('status') != 'completed' or manifest.get('reason'):
        raise ValueError('本次试写未成功完成，不生成成功存档；原始数据保留在临时失败目录')
    for name in ('sensor.csv', 'control.jsonl', 'events.jsonl', 'timeline.npz', 'compiled_plan.npz', 'setup.json', 'resolved.json'):
        if not (folder / name).is_file() or (folder / name).stat().st_size == 0:
            raise ValueError('实验数据未完整写入：' + name)
    for name, expected in manifest.get('sha256', {}).items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or file_hash(path) != expected:
            raise ValueError('实验输入快照校验失败：' + name)
    if require_tcp:
        capture = read_json(folder / 'actual_tcp_meta.json')
        if (not capture.get('worker_stopped') or capture.get('worker_error')
                or capture.get('valid_samples', 0) < 2 or capture.get('invalid_samples', 0)):
            raise ValueError('实际 TCP 采集不完整，本次数据不归档')
        if not (folder / 'actual_tcp.csv').is_file():
            raise ValueError('缺少实际 TCP 采集记录')
    return manifest


class ExperimentArchive:
    def __init__(self, root=DEFAULT_ARCHIVE_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.temporary = self.root / '.临时'
        self.temporary.mkdir(exist_ok=True)
        self.failures = self.root / '临时失败实验'
        self.failures.mkdir(exist_ok=True)

    @contextmanager
    def locked(self):
        with (self.root / '.archive.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _settings(self):
        path = self.root / '.命名设置.json'
        return read_json(path) if path.exists() else dict(version=1, last_name='毛笔试写', counters={})

    def last_name(self):
        with self.locked():
            return self._settings()['last_name']

    def _next(self, base, settings):
        pattern = re.compile(re.escape(base) + r'_(\d+)$')
        used = [int(match.group(1)) for path in self.root.iterdir()
                if (match := pattern.fullmatch(path.name))]
        number = max([settings['counters'].get(base, 0), *used]) + 1
        return number, f'{base}_{number:03d}'

    def preview_name(self, base=None):
        with self.locked():
            settings = self._settings()
            return self._next(validate_name(base if base is not None else settings['last_name']), settings)[1]

    def new_stage(self, kind='trial'):
        path = self.temporary / uuid.uuid4().hex
        path.mkdir()
        self.claim_stage(path, kind=kind)
        return path

    def claim_stage(self, path, *, kind='trial'):
        path = Path(path).resolve()
        if path.parent != self.temporary or not path.is_dir():
            raise ValueError('无效的实验临时目录')
        write_json(path / '.session.json', dict(version=1, pid=os.getpid(), process_token=_process_token(os.getpid()), kind=kind))

    def discard_stage(self, path):
        path = Path(path).resolve()
        if path.parent != self.temporary or not (path / '.session.json').is_file():
            raise ValueError('拒绝清理非本程序创建的临时目录')
        shutil.rmtree(path)

    @contextmanager
    def capture_console(self, path):
        path = Path(path)
        if isinstance(sys.stdout, _ConsoleTee) and sys.stdout.log.name == str(path / 'console.log'):
            yield
            return
        with (path / 'console.log').open('a', encoding='utf-8', buffering=1) as log:
            with redirect_stdout(_ConsoleTee(sys.stdout, log)), redirect_stderr(_ConsoleTee(sys.stderr, log)):
                yield

    @staticmethod
    def record_result(path, result):
        fields = ('state', 'run_id', 'run_dir', 'phase', 'progress', 'last_error',
                  'baseline_diagnostic', 'deadline_diagnostic', 'deadline_recovery_count',
                  'last_deadline_recovery', 'pose_capture')
        write_json(Path(path) / 'run_result.json', {key: result.get(key) for key in fields})

    def retain_stage(self, path, *, reason='execution_not_completed', exception=None):
        """Move an owned session intact, preserving every partial recording/input."""
        path = Path(path).resolve()
        if path.parent != self.temporary or not (path / '.session.json').is_file():
            raise ValueError('拒绝移动非本程序创建的临时目录')
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        try:
            result = read_json(path / 'run_result.json') if (path / 'run_result.json').is_file() else {}
        except (OSError, ValueError):
            result = {}
        recordings = []
        for manifest_path in (path / 'raw').rglob('manifest.json'):
            try:
                value = read_json(manifest_path)
                recordings.append(dict(path=manifest_path.relative_to(path).as_posix(),
                    **{key: value.get(key) for key in ('run_id', 'status', 'reason', 'started_at', 'finished_at')}))
            except (OSError, ValueError):
                continue
        recorded_reason = next((item['reason'] for item in recordings if item.get('reason')), '')
        detail = dict(version=1, retained_at=now.isoformat(), session_id=path.name,
            reason=result.get('last_error') or recorded_reason or reason, disposition=reason,
            result=result, recordings=recordings, automatically_deleted=False)
        if exception is not None:
            detail['exception'] = dict(type=type(exception).__name__, message=str(exception),
                traceback=''.join(traceback.format_exception(type(exception), exception, exception.__traceback__)))
        try:
            write_json(path / 'failure.json', detail)
            lines = ['# 未完成实验：保留用于诊断', '',
                '本目录不会被程序自动删除，也不会计入成功实验或占用成功编号。', '',
                '记录原因：`'+str(detail['reason'])+'`。', '',
                '- [失败说明与异常堆栈](failure.json)', '- [终端输出](console.log)']
            if (path / 'run_result.json').exists():
                lines.append('- [最终状态与控制周期诊断](run_result.json)')
            for item in recordings:
                manifest = Path(item['path'])
                lines += ['', '## 实验 '+str(item['run_id']), '',
                    '- [原始状态与B0基线]('+manifest.as_posix()+')']
                for name, label in [('sensor.csv', '原始磁传感数据'), ('control.jsonl', '控制反馈'),
                                    ('events.jsonl', '事件记录'), ('actual_tcp.csv', '实际TCP数据')]:
                    relative = manifest.parent / name
                    if (path / relative).exists():
                        lines.append('- ['+label+']('+relative.as_posix()+')')
            (path / 'README.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        except OSError as exc:
            print('失败说明写入失败；原始临时文件仍保留：'+str(exc), file=sys.stderr)
        # Publication of a sealed successful payload can be retried on startup.
        if (path / '.ready').exists() and (path / 'payload').exists():
            print('成功存档尚未发布，保留待恢复数据：'+str(path))
            return path
        destination = self.failures / (now.strftime('%Y-%m-%d_%H-%M-%S') + '__' + path.name)
        try:
            path.rename(destination)
        except OSError as exc:
            print('失败数据未能移入诊断目录，仍保留于 '+str(path)+'：'+str(exc), file=sys.stderr)
            return path
        print('未完成实验的全部临时数据已保留：'+str(destination))
        return destination

    @contextmanager
    def session(self, path=None):
        path = self.new_stage() if path is None else Path(path).resolve()
        if path.parent != self.temporary or not (path / '.session.json').is_file():
            raise ValueError('无效的实验临时目录')
        try:
            write_json(path / 'reproduction_environment.json', environment_snapshot())
            with self.capture_console(path):
                yield path
        except BaseException as exc:
            if path.exists():
                self.retain_stage(path, reason='session_exception', exception=exc)
            raise
        else:
            if path.exists() and (path / '.published.json').is_file():
                self.discard_stage(path)
            elif path.exists():
                self.retain_stage(path)

    def cleanup_stale(self):
        """Recover successful bundles; retain dead sessions rather than delete."""
        recovered = []
        with self.locked():
            for path in self.temporary.iterdir():
                if not path.is_dir() or path.is_symlink():
                    continue
                try:
                    owner = read_json(path / '.session.json')
                except (OSError, ValueError):
                    continue
                token = _process_token(owner.get('pid'))
                if token is not None and token == owner.get('process_token'):
                    continue
                payload = path / 'payload'
                if (path / '.ready').is_file() and payload.is_dir():
                    try:
                        verify(payload)
                        metadata = read_json(payload / 'experiment.json')
                        if not any(r['id'] == metadata['id'] for r in self.records()):
                            recovered.append(self._publish(payload, metadata['base_name']))
                    except (OSError, ValueError, KeyError):
                        # A success bundle that fails verification requires inspection;
                        # it must never be silently published or destroyed.
                        continue
                    self.discard_stage(path)
                elif (path / '.published.json').is_file():
                    self.discard_stage(path)
                else:
                    self.retain_stage(path, reason='recovered_after_unclean_shutdown')
        return recovered

    def _publish(self, payload, base):
        settings = self._settings()
        number, name = self._next(base, settings)
        metadata = read_json(payload / 'experiment.json')
        metadata.update(base_name=base, sequence=number, name=name)
        write_json(payload / 'experiment.json', metadata)
        seal_bundle(payload)
        destination = self.root / name
        if destination.exists():
            raise FileExistsError(destination)
        # Prepare the only visible file off to the side, then publish the directory
        # atomically. A compression/write failure leaves the sealed success recoverable.
        prepared = payload.parent / 'published'
        if prepared.exists():
            shutil.rmtree(prepared)
        prepared.mkdir()
        target = prepared / (name + '.brushrun')
        pack_bundle(payload, target)
        prepared.rename(destination)
        write_json(payload.parent / '.published.json', dict(id=metadata['id'], destination=str(destination)))
        shutil.rmtree(payload)
        settings['last_name'] = base
        settings['counters'][base] = number
        write_json(self.root / '.命名设置.json', settings)
        return destination

    def archive_success(self, stage, run_dir, *, input_files=None, require_tcp=False, require_editor=False):
        stage, run_dir = Path(stage), Path(run_dir)
        if stage.resolve().parent != self.temporary or not run_dir.resolve().is_relative_to(stage.resolve()):
            raise ValueError('实验记录必须位于本次临时目录')
        manifest = validate_recording(run_dir, require_tcp=require_tcp)
        payload = stage / 'payload'
        shutil.copytree(run_dir, payload)
        for name in ('console.log', 'run_result.json'):
            if (stage / name).is_file():
                shutil.copyfile(stage / name, payload / name)
        for name, data in (input_files or {}).items():
            if name not in PLAN_FILES:
                raise ValueError('不支持的实验快照文件：' + name)
            path = payload / name
            if path.exists() and path.read_bytes() != data:
                raise ValueError('执行输入与归档快照不一致：' + name)
            path.write_bytes(data)
        if require_editor:
            state = read_json(payload / 'editor_state.json')
            states = [state, *state.get('stroke_workspace', {}).get('others', [])]
            required = {'feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json'}
            if any(not isinstance(s.get('settings_snapshot'), dict) or required - s['settings_snapshot'].keys()
                   or any(s.get(k) for k in ('feedforward_override', 'settings_override', 'entry_profile_override'))
                   for s in states):
                raise ValueError('编辑状态未包含完整独立配置，禁止归档')
        # Startup positioning is already embedded in resolved.json; make its path local.
        resolved = read_json(payload / 'resolved.json')
        if resolved.get('positioning'):
            positioning = resolved['positioning']
            positioning['record_path'] = 'positioning.json'
            write_json(payload / 'positioning.json', positioning)
            write_json(payload / 'resolved.json', resolved)
            manifest['sha256']['resolved.json'] = file_hash(payload / 'resolved.json')
        write_json(payload / 'manifest.json', manifest)
        sampling = payload / 'analysis' / 'magnetic_sampling_summary.json'
        if sampling.exists():
            value = read_json(sampling)
            value.update(source_run='.', output='analysis/magnetic_timeseries.csv')
            write_json(sampling, value)
        write_json(payload / 'analysis_summary.json', summarize(payload))
        environment = stage / 'reproduction_environment.json'
        write_json(payload / 'reproduction_environment.json',
                   read_json(environment) if environment.exists() else environment_snapshot())
        with self.locked():
            base = self._settings()['last_name']
            write_json(payload / 'experiment.json', dict(version=1, id=manifest['run_id'], status='completed',
                base_name=base, name='', sequence=0, finished_at=manifest['finished_at'],
                editor_available=(payload / 'editor_state.json').is_file()))
            seal_bundle(payload)
            (stage / '.ready').touch()
            return self._publish(payload, base)

    def records(self):
        records = []
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink() or path.name.startswith('.'):
                continue
            try:
                record = read_data_json(path, 'experiment.json')
                if record.get('status') == 'completed':
                    records.append(dict(record, path=path))
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda r: r['finished_at'], reverse=True)

    def rename(self, folder, base, *, remember=False):
        folder = Path(folder).resolve()
        base = validate_name(base)
        if folder.parent != self.root:
            raise ValueError('实验目录不属于当前实验库')
        with self.locked():
            verify(folder)
            record = read_data_json(folder, 'experiment.json')
            settings = self._settings()
            if base != record['base_name']:
                number, name = self._next(base, settings)
                destination = self.root / name
                if destination.exists():
                    raise FileExistsError(destination)
                old_file = archive_path(folder)
                if not old_file.is_file():
                    raise ValueError('请先将旧目录存档转换为单文件存档')
                record.update(base_name=base, name=name, sequence=number)
                temporary = self.temporary / (uuid.uuid4().hex + '.brushrun')
                try:
                    with open_bundle(old_file) as payload:
                        write_json(payload / 'experiment.json', record)
                        seal_bundle(payload)
                        pack_bundle(payload, temporary)
                    folder.rename(destination)
                    try:
                        temporary.replace(destination / (name + '.brushrun'))
                    except BaseException:
                        destination.rename(folder)
                        raise
                    if old_file.name != name + '.brushrun':
                        (destination / old_file.name).unlink()
                    folder = destination
                finally:
                    temporary.unlink(missing_ok=True)
                settings['counters'][base] = number
            if remember:
                settings['last_name'] = base
            write_json(self.root / '.命名设置.json', settings)
            return folder
