import copy
import json
import numpy as np
import pytest


def fields(points=None, seed=101, parameters=None):
    from brushbot.experiments.stroke_variation import generate_fields
    return generate_fields(np.array(points if points is not None else [[0.,0.],[100.,0.]]),
                           root_seed=seed, stroke_id='heng', parameters=parameters or {})


def test_seed_changes_actual_values_but_replays_exactly():
    from brushbot.experiments.stroke_variation import evaluate_fields
    a,b=fields(),fields(seed=202)
    assert a==fields() and a==json.loads(json.dumps(a))
    x,g=evaluate_fields(a,np.linspace(0,1,1001))
    y,h=evaluate_fields(b,np.linspace(0,1,1001))
    assert np.max(abs(x))>0 and np.max(abs(g))>0
    assert not np.array_equal(x,y) and not np.array_equal(g,h)
    assert np.array_equal(x[[0,-1]],np.zeros((2,2)))
    assert np.array_equal(g[[0,-1]],np.zeros(2))


def test_channel_streams_are_independent():
    from brushbot.experiments.stroke_variation import evaluate_fields
    a=fields();b=fields(parameters={'magnetic_global_max':.01})
    q=np.linspace(0,1,101)
    assert np.array_equal(evaluate_fields(a,q)[0],evaluate_fields(b,q)[0])


@pytest.mark.parametrize('points',[
    [[0.,0.],[100.,0.]],[[0.,0.],[.03,0.]],
    [[0.,0.],[5.,0.],[0.,0.],[0.,5.]],
    [[0.,0.],[5.,5.],[0.,5.],[5.,0.]],
])
def test_displacement_and_gain_bounds(points):
    from brushbot.experiments.stroke_variation import varied_path,evaluate_fields
    f=fields(points);result=varied_path(np.array(points),f)
    assert np.array_equal(result['execution_xy_mm'][[0,-1]],np.array(points)[[0,-1]])
    assert len(result['execution_xy_mm'])>2
    assert np.all(np.diff(result['execution_s'])>0)
    x,g=evaluate_fields(f,np.linspace(0,1,2001))
    length=np.linalg.norm(np.diff(points,axis=0),axis=1).sum()
    assert np.linalg.norm(x,axis=1).max()<=min(.005*length,.30)+1e-12
    assert abs(g).max()<=.07+1e-12
    # A nonzero endpoint slope would make displacement / progress approach a constant.
    tiny=evaluate_fields(f,np.array([1e-8,1-1e-8]))[0]
    assert abs(tiny).max()<1e-14


@pytest.mark.parametrize('parameters',[{'xy_absolute_max_mm':True},{'magnetic_local_max':float('nan')},
    {'magnetic_global_max':1.},{'unknown':1.},{'xy_relative_max':-1.}])
def test_invalid_parameters_rejected(parameters):
    with pytest.raises(ValueError):fields(parameters=parameters)


def test_invalid_fields_and_duplicate_path_rejected():
    from brushbot.experiments.stroke_variation import evaluate_fields
    with pytest.raises(ValueError):fields([[0.,0.],[0.,0.]])
    f=fields();f['version']=99
    with pytest.raises(ValueError):evaluate_fields(f,np.array([.5]))
    f=fields();f['local_xy_mm'][0]=[500.,0.]
    with pytest.raises(ValueError):evaluate_fields(f,np.array([.5]))
