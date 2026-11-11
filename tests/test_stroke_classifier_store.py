import json
from pathlib import Path
import pytest


def test_history_rename_favorite_delete_restore_preserves_sources(tmp_path):
    from brushbot.stroke_classification.store import ModelStore
    store=ModelStore(tmp_path/'store')
    original=tmp_path/'source.brushrun';original.write_bytes(b'original experiment')
    task=store.create_task('训练A',{'sources':[str(original)]})
    model=store.add_model(task,{'name':'幅值','metrics':{}},{'value':42})
    store.complete(task)
    store.rename(task['id'],'重命名')
    store.favorite(task['id'],True)
    assert store.list_tasks()[0]['name']=='重命名'
    assert store.list_tasks()[0]['favorite']
    store.delete(task['id'],model['id'])
    assert store.list_tasks()==[]
    assert original.read_bytes()==b'original experiment'
    store.restore(task['id'])
    assert store.load_bundle(task['id'],model['id'])['value']==42
    store.delete(task['id'])
    assert store.list_tasks()==[]
    store.restore(task['id'])
    assert len(store.list_tasks())==1
    assert original.exists()


def test_bad_ids_cannot_escape_store(tmp_path):
    from brushbot.stroke_classification.store import ModelStore
    with pytest.raises(ValueError): ModelStore(tmp_path).delete('../elsewhere')


def test_corrupted_bundle_is_rejected_before_deserialization(tmp_path):
    from brushbot.stroke_classification.store import ModelStore
    store=ModelStore(tmp_path/'store');task=store.create_task('a',{})
    model=store.add_model(task,{'name':'test'},{'value':42});store.complete(task)
    (store.model_path(task['id'],model['id'])/'bundle.joblib').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='校验'):store.load_bundle(task['id'],model['id'])


def test_export_import_reuses_model_without_training(tmp_path):
    from brushbot.stroke_classification.store import ModelStore
    from brushbot.stroke_classification import VERSION
    store=ModelStore(tmp_path/'first');task=store.create_task('a',{'version':VERSION})
    model=store.add_model(task,{'name':'test'},{'value':42});store.complete(task)
    package=store.export(task['id'],tmp_path/'model.zip')
    other=ModelStore(tmp_path/'second');restored=other.import_package(package)
    assert restored['id']==task['id']
    assert other.load_bundle(task['id'],model['id'])['value']==42


def test_import_package_cannot_write_outside_task(tmp_path):
    import zipfile
    from brushbot.stroke_classification.store import ModelStore
    target=tmp_path/'bad.zip'
    with zipfile.ZipFile(target,'w') as z:z.writestr('../../escape','bad')
    with pytest.raises(ValueError):ModelStore(tmp_path/'store').import_package(target)
    assert not (tmp_path/'escape').exists()
