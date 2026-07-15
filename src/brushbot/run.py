def run(backend, controller, on_tick=None):
    """定频跑 read->step->write，直到 controller.done()。每拍回调 on_tick(state)。"""
    while not controller.done():
        st = backend.read()
        cmd = controller.step(st)
        backend.write(cmd)
        if on_tick is not None:
            on_tick(backend.read())
