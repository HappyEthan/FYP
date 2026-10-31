import csv
import json

import pytest

from scripts.record_manual_brush import prepare_session, refresh_index


def test_new_batch_is_separate_and_does_not_claim_measurements(tmp_path):
    folder = prepare_session(tmp_path)
    assert folder.parent.parent.name == 'manual'
    assert all((folder/name).is_dir() for name in ['raw', 'media', 'analysis'])
    metadata = json.loads((folder/'session.json').read_text())
    assert metadata['xy_recorded'] is False
    assert metadata['paper'] is None
    assert metadata['sensor_tip_offset_mm']['measured'] is False
    assert list(csv.DictReader((folder/'records.csv').open())) == []


def test_refresh_keeps_manual_labels_and_raw_bytes(tmp_path):
    folder = prepare_session(tmp_path)
    raw = folder/'raw'/'example.csv'
    raw.write_text('t_us,t_s,dBx_uT,dBy_uT,dBz_uT,sample_valid\n0,0,1,2,3,1\n')
    (folder/'raw'/'example.json').write_text(json.dumps(dict(sample_count=1, measured_duration_s=0., valid=True)))
    original = raw.read_bytes()
    assert refresh_index(folder) == 1
    with (folder/'records.csv').open() as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        row = next(reader)
    row.update(action='dot_retract', photo='media/example_ink.jpeg', note='good shape')
    with (folder/'records.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    refresh_index(folder)
    with (folder/'records.csv').open() as stream:
        updated = next(csv.DictReader(stream))
    assert updated['action'] == 'dot_retract'
    assert updated['photo'] == 'media/example_ink.jpeg'
    assert updated['note'] == 'good shape'
    assert raw.read_bytes() == original


def test_batch_name_cannot_escape_the_manual_root(tmp_path):
    with pytest.raises(ValueError):
        prepare_session(tmp_path, label='../robot-run')
