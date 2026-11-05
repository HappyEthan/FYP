"""Read and verify portable .brushrun files using only the standard library."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile


def archive_path(path):
    """Resolve an experiment folder or a directly selected archive file."""
    path = Path(path)
    if path.is_dir():
        archives = list(path.glob('*.brushrun'))
        if len(archives) > 1:
            raise ValueError('目录包含多个实验存档，请选择具体的 .brushrun 文件')
        if archives:
            return archives[0]
    return path


def read_bytes(path, name):
    path = archive_path(path)
    if path.is_dir():
        return (path / name).read_bytes()
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.read(name)
    except KeyError as exc:
        raise FileNotFoundError('实验存档缺少数据：' + name) from exc
    except zipfile.BadZipFile as exc:
        raise ValueError('实验存档损坏：' + name) from exc


def read_json(path, name):
    return json.loads(read_bytes(path, name).decode('utf-8'))


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify(folder):
    folder = archive_path(folder)
    if folder.is_file():
        try:
            with zipfile.ZipFile(folder) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ValueError('实验存档包含重复文件')
                for name in names:
                    parts = PurePosixPath(name)
                    if parts.is_absolute() or '..' in parts.parts or '\\' in name or str(parts) != name:
                        raise ValueError('实验存档包含非法路径：' + name)
                manifest = json.loads(archive.read('bundle_manifest.json'))
                if manifest.get('version') != 1 or manifest.get('format') != 'brushrun':
                    raise ValueError('不支持的实验存档格式或版本')
                hashes = manifest['sha256']
                if set(names) != set(hashes) | {'bundle_manifest.json'}:
                    raise ValueError('实验存档文件清单不完整')
                for name, expected in hashes.items():
                    digest = hashlib.sha256()
                    with archive.open(name) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(chunk)
                    if digest.hexdigest() != expected:
                        raise ValueError('文件校验失败：' + name)
                return len(hashes)
        except (zipfile.BadZipFile, KeyError, TypeError) as exc:
            raise ValueError('实验存档损坏或格式不完整') from exc
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'bundle_manifest.json').read_text(encoding='utf-8'))
    errors = []
    for name, expected in manifest['sha256'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or file_hash(path) != expected:
            errors.append(name)
    if errors:
        raise ValueError('文件缺失或校验失败：' + '、'.join(errors))
    return len(manifest['sha256'])


@contextmanager
def open_bundle(path):
    """Expose verified data temporarily for consumers needing filesystem paths."""
    path = archive_path(path)
    verify(path)
    if path.is_dir():
        yield path
        return
    with tempfile.TemporaryDirectory(prefix='brushrun-') as temporary:
        folder = Path(temporary)
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
        yield folder


def load_control(folder):
    return [json.loads(line) for line in read_bytes(folder, 'control.jsonl').splitlines() if line.strip()]


def summarize(folder):
    """Recompute defined metrics directly from recorded feedback, without resampling."""
    rows = load_control(folder)
    writing = [row for row in rows if str(row.get('phase', '')).startswith('measure_')]
    values = [(float(row['a_ref_uT']), float(row['a_control_uT'])) for row in writing
              if all(isinstance(row.get(key), (int, float)) and math.isfinite(row[key])
                     for key in ('a_ref_uT', 'a_control_uT'))]
    errors = [actual - target for target, actual in values]
    result = dict(control_samples=len(rows), writing_samples=len(writing),
                  valid_target_response_pairs=len(values),
                  magnetic_rmse_uT=math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
                  magnetic_mae_uT=sum(abs(e) for e in errors) / len(errors) if errors else None,
                  magnetic_mean_error_uT=sum(errors) / len(errors) if errors else None,
                  metric_definition='measure_* ticks; recorded a_control_uT minus a_ref_uT; no resampling')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='校验实验文件，并从原始控制记录重新计算磁目标跟踪指标。')
    parser.add_argument('folder', type=Path, help='.brushrun 存档文件或实验文件夹')
    parser.add_argument('--output', type=Path, help='可选：另存重新计算的指标 JSON')
    args = parser.parse_args(argv)
    count = verify(args.folder)
    result = summarize(args.folder)
    print(f'校验通过：{count} 个文件。')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
