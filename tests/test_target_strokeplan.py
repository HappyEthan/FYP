import copy
import numpy as np
import pytest


def target():
    from brushbot.target_strokeplan import Stroke, StrokePlan
    return StrokePlan([Stroke(np.array([0., .5, .5, 1.]),
        np.array([[0., 0.], [.01, 0.], [.01, 0.], [.02, 0.]]),
        np.array([0., 1., 2., 3.]), np.array([30., 40., 40., 50.]))],
        dict(source='synthetic', coordinate_frame='paper',
             feature='filtered_dBxy_norm_uT', filter_definition={'kind':'ema','alpha':.3}))


def test_roundtrip_with_pause_and_no_z(tmp_path):
    p = target()
    path = tmp_path/'target.npz'
    p.save(path)
    with np.load(path, allow_pickle=False) as data:
        assert 's0_z' not in data.files
        assert int(data['format_version']) == 3
    q = type(p).load(path)
    assert q.strokes[0].t.tolist() == [0., 1., 2., 3.]
    assert q.strokes[0].xy.tolist() == p.strokes[0].xy.tolist()
    with pytest.raises(FileExistsError):
        p.save(path)


@pytest.mark.parametrize('field,value', [
    ('t',[0,1,1,3]), ('t',[0,1,float('nan'),3]), ('t',[0,1]),
    ('g_target',[30,-1,40,50]), ('s',[0,.3,.3,1]),
    ('xy',[[0,0]]*4), ('xy',[[0,0,0]]*4)])
def test_invalid_arrays_rejected(field,value):
    p = target()
    setattr(p.strokes[0],field,np.array(value))
    with pytest.raises(ValueError):
        p.validate()


@pytest.mark.parametrize('key',['z','z_ff','z_demo','z_cmd','reference_table','setup',
                              'feedforward_table','depth_m','surface_z_mm'])
def test_nested_device_data_rejected(key):
    p = target()
    p.meta['nested'] = {key: [1]}
    with pytest.raises(ValueError):
        p.validate()


def test_loader_rejects_old_version_and_unexpected_z(tmp_path):
    p = target()
    p.save(tmp_path/'p.npz')
    with np.load(tmp_path/'p.npz') as d:
        arrays = dict(d)
    for name, changes in [('old',dict(format_version=2)), ('extra',dict(s0_z=[0]*4)),
                           ('missing',{})]:
        a = copy.deepcopy(arrays)
        a.update(changes)
        if name == 'missing':
            del a['s0_t']
        np.savez(tmp_path/f'{name}.npz',**a)
        with pytest.raises(ValueError):
            type(p).load(tmp_path/f'{name}.npz')
