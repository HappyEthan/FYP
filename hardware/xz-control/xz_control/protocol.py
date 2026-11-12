"""Transport-independent validation and demo. Demo never opens a serial device."""
import math
import time

PROTOCOL = "XZ1"
PROTOCOL_INT_MAX = 2_147_483_647  # ESP32 signed 32-bit command representation.
PROTOCOL_INT_MIN = -2_147_483_648
DEFAULT_ACCEL = 1000
ERRORS = {
    'JOG_TIMEOUT': '点动按住信号超时，已停止；请复位故障并重新确认零点',
    'NOT_ARMED': '请先使能运动', 'BUSY': '运动中，不能修改目标或零点',
    'ZERO_REQUIRED': '请先确认并设置两轴零点', 'NO_HEARTBEAT': '通信心跳未就绪',
    'SPEED_LIMIT': '设备仍在限制速度，请上传新版双轴固件',
    'BAD_SPEED': '速度必须为正整数', 'MOVE_LIMIT': '设备仍有旧版位移限制，请上传新版固件', 'NUMERIC_RANGE': '数值或目标差值超出控制器 32 位整数运算范围',
    'BAD_ACCEL': '加速度必须为正整数',
    'BAD_NUMBER': '数值格式错误', 'BAD_ORDER': '运动顺序错误', 'BAD_MODE': '坐标模式错误',
    'FAULT_LOCKED': '故障已锁定，请检查后复位', 'LINK_TIMEOUT': '通信心跳超时，已停止并取消使能',
    'BAD_COMMAND': '命令不受支持', 'LINE_TOO_LONG': '命令过长', 'BAD_AXIS': '轴名称错误',
}

def move_command(mode, order, x, z, vx, vz, current, ax=DEFAULT_ACCEL, az=DEFAULT_ACCEL):
    if mode not in ('ABS', 'REL') or order not in ('XZ', 'ZX', 'SIM'):
        raise ValueError('无效的运动方式')
    values = (x, z, vx, vz, ax, az)
    if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        raise ValueError('请输入整数脉冲、速度和加速度')
    if vx < 1 or vz < 1:
        raise ValueError(ERRORS['BAD_SPEED'])
    if vx > PROTOCOL_INT_MAX or vz > PROTOCOL_INT_MAX:
        raise ValueError('速度数值超出串口协议的 32 位整数范围')
    if ax < 1 or az < 1:
        raise ValueError(ERRORS['BAD_ACCEL'])
    if ax > PROTOCOL_INT_MAX or az > PROTOCOL_INT_MAX:
        raise ValueError('加速度数值超出串口协议的 32 位整数范围')
    tx, tz = (x, z) if mode == 'ABS' else (current['x'] + x, current['z'] + z)
    if any(not PROTOCOL_INT_MIN <= v <= PROTOCOL_INT_MAX for v in (x,z,tx,tz)) or any(
            abs(t-current[a]) > PROTOCOL_INT_MAX for a,t in (('x',tx),('z',tz))):
        raise ValueError(ERRORS['NUMERIC_RANGE'])
    return f'MOVE {mode} {order} {x} {z} {vx} {vz} {ax} {az}'

def motion_profile(distance, speed, accel):
    """Ideal rest-to-rest trapezoid; no pulse quantization or hardware timing model."""
    distance = abs(distance)
    peak = min(speed, math.sqrt(distance * accel))
    ramp_time = peak / accel
    cruise_distance = max(0.0, distance - peak * ramp_time)
    cruise_time = cruise_distance / peak if peak else 0.0
    return dict(distance=distance, peak=peak, ramp_time=ramp_time,
                cruise_distance=cruise_distance, cruise_time=cruise_time,
                duration=2 * ramp_time + cruise_time)

def profile_sample(profile, elapsed, accel):
    """Return ideal distance travelled and speed at elapsed seconds."""
    p = profile; t = max(0.0, elapsed)
    if t >= p['duration']: return p['distance'], 0.0
    if t < p['ramp_time']: return .5 * accel * t * t, accel * t
    if t < p['ramp_time'] + p['cruise_time']:
        return (.5 * p['peak'] * p['ramp_time'] +
                p['peak'] * (t - p['ramp_time']), p['peak'])
    left = p['duration'] - t
    return p['distance'] - .5 * accel * left * left, accel * left

def parse_status(data):
    if data.get('protocol') != PROTOCOL or data.get('type') != 'status':
        raise ValueError('固件协议不兼容')
    for key in ('armed', 'busy', 'phase', 'x', 'z', 'tx', 'tz', 'refx', 'refz'):
        if type(data.get(key)) is not int:
            raise ValueError('状态数据格式错误')
    for key in ('x', 'z', 'tx', 'tz'):
        if not PROTOCOL_INT_MIN <= data[key] <= PROTOCOL_INT_MAX:
            raise ValueError('状态位置越界')
    for key in ('armed', 'busy', 'refx', 'refz'):
        if data[key] not in (0, 1):
            raise ValueError('状态标志错误')
    if data['phase'] not in (0, 1, 2, 3) or not isinstance(data.get('fault'), str):
        raise ValueError('状态阶段错误')
    for key in ('vx', 'vz'):
        if type(data.get(key)) not in (int, float) or not math.isfinite(data[key]):
            raise ValueError('状态速度错误')
    return data

class Simulator:
    """Ideal acceleration/cruise/deceleration demo, NOT hardware validation."""
    def __init__(self):
        self.s = dict(type='status', protocol=PROTOCOL, armed=0, busy=0, phase=0,
                      x=0, z=0, tx=0, tz=0, vx=0.0, vz=0.0, refx=0, refz=0, fault='NONE')
        self.pos = {'x': 0.0, 'z': 0.0}
        self.speeds = {'x': 10, 'z': 10}
        self.plans = {}
        self.jog_axis = None; self.jog_lease = 0.; self.jog_releasing = False

    def halt(self):
        self.jog_axis = None; self.jog_releasing = False
        if self.s['busy']:
            self.s['refx'] = self.s['refz'] = 0
        self.s.update(armed=0, busy=0, phase=0, vx=0.0, vz=0.0,
                      tx=self.s['x'], tz=self.s['z'])
        self.pos = {a: float(self.s[a]) for a in ('x', 'z')}

    def plan_move(self, mode, order, x, z, vx, vz, ax, az):
        self.s.update(tx=x + (self.s['x'] if mode == 'REL' else 0),
                      tz=z + (self.s['z'] if mode == 'REL' else 0),
                      busy=1, phase={'XZ': 1, 'ZX': 2, 'SIM': 3}[order])
        self.speeds = dict(x=vx, z=vz)
        for a, accel in (('x', ax), ('z', az)):
            delta = self.s['t' + a] - self.pos[a]
            self.plans[a] = dict(profile=motion_profile(delta, self.speeds[a], accel),
                                 elapsed=0.0, start=self.pos[a],
                                 direction=1 if delta >= 0 else -1, accel=accel)

    def command(self, line):
        parts = line.split(); cmd = parts[0]
        if cmd == 'JOG':
            if self.s['fault'] != 'NONE': return [{'type':'error','code':'FAULT_LOCKED'}]
            if not self.s['armed']: return [{'type':'error','code':'NOT_ARMED'}]
            if self.s['busy']: return [{'type':'error','code':'BUSY'}]
            axis=parts[1].lower(); direction,speed,accel=map(int,parts[2:])
            if axis not in ('x','z') or direction not in (-1,1): raise ValueError('无效点动参数')
            dest=PROTOCOL_INT_MAX if direction > 0 else PROTOCOL_INT_MIN
            if dest==self.s[axis]: return [{'type':'error','code':'NUMERIC_RANGE'}]
            x=dest if axis=='x' else self.s['x']; z=dest if axis=='z' else self.s['z']
            if not 1 <= speed <= PROTOCOL_INT_MAX or not 1 <= accel <= PROTOCOL_INT_MAX:
                raise ValueError('速度和加速度必须为正的 32 位整数')
            self.plan_move('ABS', 'SIM', x, z, speed, speed, accel, accel)
            self.jog_axis=axis; self.jog_lease=.35; self.jog_releasing=False
        elif cmd == 'JKEEP':
            if self.jog_axis and not self.jog_releasing: self.jog_lease=.35
            return []
        elif cmd == 'JEND':
            if self.jog_axis and not self.jog_releasing:
                a=self.jog_axis; plan=self.plans[a]; speed=abs(self.s['v'+a])
                distance=min(abs(self.s['t'+a]-self.pos[a]), speed*speed/(2*plan['accel']))
                # Round endpoint to pulse count, with an ideal braking curve to that endpoint.
                target=round(self.pos[a]+plan['direction']*distance)
                distance=abs(target-self.pos[a]); accel=speed*speed/(2*distance) if distance and speed else plan['accel']
                self.s['t'+a]=target
                plan.update(start=self.pos[a],elapsed=0.,accel=accel,
                            profile=dict(distance=distance,peak=speed,ramp_time=0.,cruise_time=0.,
                                         duration=2*distance/speed if speed else 0.))
                self.jog_releasing=True
        elif cmd in ('STOP', 'DISARM'):
            self.halt()
        elif cmd == 'CLEAR':
            self.halt(); self.s['fault'] = 'NONE'
        elif cmd == 'ZERO':
            if self.s['busy']: return [{'type': 'error', 'code': 'BUSY'}]
            for a in ('x', 'z') if parts[1] == 'ALL' else (parts[1].lower(),):
                self.s[a] = self.s['t' + a] = 0
                self.s['ref' + a] = 1; self.pos[a] = 0.0
        elif cmd == 'ARM':
            if not self.s['refx'] or not self.s['refz']:
                return [{'type': 'error', 'code': 'ZERO_REQUIRED'}]
            self.s['armed'] = 1
        elif cmd == 'MOVE':
            if not self.s['armed']: return [{'type': 'error', 'code': 'NOT_ARMED'}]
            if self.s['busy']: return [{'type': 'error', 'code': 'BUSY'}]
            if len(parts) not in (7, 9): return [{'type': 'error', 'code': 'BAD_COMMAND'}]
            mode, order = parts[1:3]; x, z, vx, vz = map(int, parts[3:7])
            ax, az = map(int, parts[7:]) if len(parts) == 9 else (50, 50)
            move_command(mode, order, x, z, vx, vz, self.s, ax, az)
            self.plan_move(mode, order, x, z, vx, vz, ax, az)
        elif cmd == 'PING':
            return []
        elif cmd == 'STATUS':
            return [self.s.copy()]
        else:
            return [{'type': 'error', 'code': 'BAD_COMMAND'}]
        return [{'type': 'ack', 'cmd': cmd}, self.s.copy()]

    def tick(self, dt):
        s = self.s
        if self.jog_axis and not self.jog_releasing:
            self.jog_lease -= dt
            if self.jog_lease <= 0:
                self.halt(); self.s['fault']='JOG_TIMEOUT'
                return [self.s.copy()]
        remaining = max(0.0, dt)
        while s['busy'] and s['armed']:
            axes = ('x',) if s['phase'] == 1 else ('z',) if s['phase'] == 2 else ('x', 'z')
            stage_left = max(self.plans[a]['profile']['duration'] - self.plans[a]['elapsed'] for a in axes)
            step_time = min(remaining, max(0.0, stage_left))
            for a in ('x', 'z'):
                s['v' + a] = 0.0
            for a in axes:
                plan = self.plans[a]
                plan['elapsed'] = min(plan['elapsed'] + step_time, plan['profile']['duration'])
                travelled, speed = profile_sample(plan['profile'], plan['elapsed'], plan['accel'])
                self.pos[a] = plan['start'] + plan['direction'] * travelled
                s[a] = int(round(self.pos[a]))
                s['v' + a] = plan['direction'] * speed
            done = lambda a: self.plans[a]['elapsed'] >= self.plans[a]['profile']['duration']
            if s['phase'] == 1 and done('x'): s['phase'] = 3
            elif s['phase'] == 2 and done('z'): s['phase'] = 3
            if all(done(a) for a in ('x', 'z')):
                self.jog_axis=None; self.jog_releasing=False
                s.update(busy=0, phase=0, vx=0.0, vz=0.0)
                return [{'type': 'done'}, s.copy()]
            remaining -= step_time
            if remaining <= 0: break
        return [s.copy()]
