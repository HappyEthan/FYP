"""Physical units and declarative, versioned motion recipes; never opens devices."""
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from xz_control.protocol import move_command, motion_profile


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
        raise ValueError(f'{label}必须是有限数字')
    return value


@dataclass
class AxisConfig:
    x_ppmm: float = 250.
    z_ppmm: float = 250.
    x_speed: float = 1.
    z_speed: float = 1.
    x_accel: float = 2.
    z_accel: float = 2.
    x_right: int = 1
    x_min: float | None = None
    x_max: float | None = None
    z_min: float | None = None
    z_max: float | None = None

    def validate(self):
        for axis in ('x','z'):
            for suffix in ('ppmm','speed','accel'):
                if finite(getattr(self,f'{axis}_{suffix}'),f'{axis} {suffix}')<=0:
                    raise ValueError('脉冲换算、速度和加速度必须大于 0')
            lo,hi=(getattr(self,f'{axis}_{b}') for b in ('min','max'))
            for val in (lo,hi):
                if val is not None: finite(val,'行程边界')
            if lo is not None and hi is not None and lo>=hi: raise ValueError('最小边界必须小于最大边界')
        if type(self.x_right) is not int or self.x_right not in (-1,1): raise ValueError('X 右方向必须为 ±1')
        return self

    def to_dict(self): return asdict(self)

    def direction(self, direction):
        return {'left':('X',-self.x_right),'right':('X',self.x_right),
                'up':('Z',-1),'down':('Z',1)}[direction]

    def pulses(self, axis, value):
        value=finite(value,'距离/位置')
        pulses=round(value*getattr(self,axis.lower()+'_ppmm'))
        if value!=0 and pulses==0: raise ValueError('距离小于一个脉冲，无法执行')
        return pulses

    def check_position(self,x,z):
        for axis,position in (('x',x),('z',z)):
            mm=position/getattr(self,axis+'_ppmm')
            lo,hi=(getattr(self,f'{axis}_{b}') for b in ('min','max'))
            if (lo is not None and mm<lo) or (hi is not None and mm>hi):
                raise ValueError(f'{axis.upper()} 目标超过所设软件边界')

    def without_bounds(self):
        values=self.to_dict()
        for axis in ('x','z'):
            for bound in ('min','max'): values[f'{axis}_{bound}']=None
        return AxisConfig(**values)


@dataclass
class Step:
    kind: str = 'relative'
    axis: str = 'X'
    value: float = 1.
    speed: float | None = None
    accel: float | None = None
    duration: float = 0.
    enabled: bool = True
    label: str = ''


@dataclass
class Recipe:
    name: str = '未命名流程'
    steps: list[Step] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    def config_changed(self, config):
        return bool(self.config and self.config!=config.to_dict())


@dataclass
class PlannedStep:
    index: int
    x: int
    z: int
    command: str | None
    duration: float
    label: str


def plan_steps(recipe, current, config):
    config.validate()
    if not recipe.steps: raise ValueError('请至少添加一个动作')
    x,z=int(current['x']),int(current['z'])
    planned=[]
    for index,step in enumerate(recipe.steps,1):
        if type(step.enabled) is not bool: raise ValueError('启用标记必须是布尔值')
        if not step.enabled: continue
        if step.kind=='wait':
            if finite(step.duration,'等待时间')<0: raise ValueError('等待时间不能为负数')
            planned.append(PlannedStep(index,x,z,None,step.duration,step.label)); continue
        if step.kind not in ('relative','absolute','zero') or step.axis not in ('X','Z'):
            raise ValueError(f'第 {index} 步动作或轴无效')
        a=step.axis.lower()
        speed=finite(getattr(config,a+'_speed') if step.speed is None else step.speed,'速度')
        accel=finite(getattr(config,a+'_accel') if step.accel is None else step.accel,'加速度')
        if speed<=0 or accel<=0: raise ValueError('速度和加速度必须大于 0')
        n=0 if step.kind=='zero' else config.pulses(a,step.value)
        tx,tz=x,z
        target=(x if a=='x' else z)+n if step.kind=='relative' else n
        if a=='x': tx=target
        else: tz=target
        speeds={axis:round(getattr(config,axis+'_speed')*getattr(config,axis+'_ppmm')) for axis in ('x','z')}
        accels={axis:round(getattr(config,axis+'_accel')*getattr(config,axis+'_ppmm')) for axis in ('x','z')}
        speeds[a]=round(speed*getattr(config,a+'_ppmm'))
        accels[a]=round(accel*getattr(config,a+'_ppmm'))
        command=move_command('ABS','SIM',tx,tz,speeds['x'],speeds['z'],{'x':x,'z':z},accels['x'],accels['z'])
        config.check_position(tx,tz)
        distance=abs(target-(x if a=='x' else z))
        duration=motion_profile(distance,speeds[a],accels[a])['duration']
        planned.append(PlannedStep(index,tx,tz,command,duration,step.label))
        x,z=tx,tz
    if not planned: raise ValueError('没有启用的动作')
    return planned


def save_recipe(path,recipe):
    payload={'version':1,'name':recipe.name,'config':recipe.config,'steps':[asdict(s) for s in recipe.steps]}
    path=Path(path); tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    tmp.replace(path)


def load_recipe(path):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('version')!=1: raise ValueError('不支持的流程文件版本')
        name=data['name']; raw=data['steps']; cfg=data.get('config',{})
        if not isinstance(name,str) or not isinstance(raw,list) or not isinstance(cfg,dict): raise ValueError('流程格式错误')
        if len(raw)>1000: raise ValueError('流程最多支持 1000 步')
        config=AxisConfig(**cfg) if cfg else AxisConfig()
        config.validate()
        recipe=Recipe(name,[Step(**s) for s in raw],cfg)
        # Validate types and pulse ranges; position-dependent bounds are checked at execution.
        plan_steps(recipe,{'x':0,'z':0},config.without_bounds())
        return recipe
    except (KeyError,TypeError,OverflowError,json.JSONDecodeError) as exc:
        raise ValueError('流程文件内容无效') from exc
