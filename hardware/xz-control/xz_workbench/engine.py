"""Single-owner, nonblocking motion coordinator independent of Qt and serial."""
from xz_control.protocol import parse_status
from .model import AxisConfig, Recipe, Step, plan_steps


class Engine:
    def __init__(self,send,clock,emit=lambda event:None):
        self.send=send; self.clock=clock; self.emit=emit
        self.config=AxisConfig(); self.status=None; self.ready=False
        self.last_status=0.; self.pending=None; self.pending_at=0.
        self.owner=None; self.recording=False; self.stage='manual_idle'
        self.steps=[]; self.step_pos=0; self.active=None
        self.acked=False; self.done=False; self.verified=False
        self.wait_until=None; self.deadline=None; self.lease_at=0.
        self.releasing=False; self.last_keep=0.; self.error=''
        self.motion_timeout=600.

    def notify(self,kind,**payload): self.emit(dict(type=kind,**payload))

    def connect(self,status):
        self.ready=True; self.status=parse_status(dict(status)); self.last_status=self.clock()
        self.error=''; self.notify('connected')

    def disconnect(self,reason='已断开'):
        if self.ready: self.stop(reason)
        self.ready=False; self.status=None; self.pending=None

    def idle(self):
        return bool(self.ready and self.status and not self.status['busy'] and not self.pending and self.owner is None)

    def require_idle(self,armed=False):
        if not self.idle(): raise ValueError('请先连接并等待当前运动/指令结束')
        if self.clock()-self.last_status>1.5: raise ValueError('控制器状态已过期')
        if self.status['fault']!='NONE': raise ValueError('控制器故障，检查后复位')
        if armed and not (self.status['armed'] and self.status['refx'] and self.status['refz']):
            raise ValueError('请先设置两轴软件零点并使能运动')

    def issue(self,line):
        self.pending=line.split()[0]; self.pending_at=self.clock(); self.send(line)

    def configure(self,config):
        if self.owner or self.pending or self.recording or (self.status and self.status['busy']):
            raise ValueError('运动或录制期间不能修改配置')
        self.config=config.validate()

    def zero(self,axis):
        self.require_idle()
        if self.recording: raise ValueError('录制期间不能改变坐标零点')
        if axis not in ('X','Z','ALL'): raise ValueError('无效轴')
        self.issue('ZERO '+axis)
        self.config=self.config.without_bounds()
        self.notify('origin_changed',config=self.config.to_dict())

    def arm(self):
        self.require_idle()
        if not self.status['refx'] or not self.status['refz']: raise ValueError('请先设置两轴软件零点')
        self.issue('ARM')

    def clear(self):
        if not self.idle(): raise ValueError('请先停止运动')
        self.issue('CLEAR')

    def run(self,recipe):
        self.require_idle(armed=True)
        if recipe.config_changed(self.config): raise ValueError('流程配置与当前配置不同，请检查并另存流程后重试')
        planned=plan_steps(recipe,self.status,self.config)
        if any(s.duration*2+5>self.motion_timeout for s in planned if s.command):
            raise ValueError('单步预计时间超过运动超时上限，请缩短动作或调整速度')
        self.steps=planned; self.step_pos=0; self.owner='recipe'; self.error=''
        self.notify('started',name=recipe.name,count=len(planned)); self.advance()

    def move(self,step):
        self.run(Recipe('手动定距/定位',[step])); self.owner='manual'
        self.stage='manual_move_'+step.axis.lower()

    def advance(self):
        if self.step_pos>=len(self.steps):
            self.owner=None; self.active=None; self.wait_until=None; self.deadline=None
            self.stage='manual_idle'; self.notify('complete'); return
        step=self.steps[self.step_pos]; self.active=step
        self.acked=self.done=self.verified=False
        self.stage=f'step_{step.index:03d}'
        self.notify('step',index=step.index,number=self.step_pos+1,count=len(self.steps),x=step.x,z=step.z)
        if step.command:
            self.deadline=self.clock()+max(5.,step.duration*2+5)
            self.issue(step.command)
        else:
            self.deadline=None; self.wait_until=self.clock()+step.duration

    def jog(self,axis,direction):
        self.require_idle(armed=True)
        if axis not in ('X','Z') or direction not in (-1,1): raise ValueError('无效点动方向')
        a=axis.lower(); self.config.validate()
        speed=round(getattr(self.config,a+'_speed')*getattr(self.config,a+'_ppmm'))
        accel=round(getattr(self.config,a+'_accel')*getattr(self.config,a+'_ppmm'))
        if not 1<=speed<=2147483647 or not 1<=accel<=2147483647: raise ValueError('速度或加速度超出有效脉冲范围')
        # Leave braking distance + status/report and scheduling margin before a configured boundary.
        self.jog_axis=a; self.jog_direction=direction
        self.jog_speed=speed; self.jog_accel=accel
        self.check_jog_boundary()
        self.owner='jog'; self.releasing=False; self.lease_at=self.clock(); self.last_keep=self.clock()
        self.stage='manual_jog_'+a
        self.issue(f'JOG {axis} {direction} {speed} {accel}')

    def check_jog_boundary(self):
        a=self.jog_axis; sign=self.jog_direction
        bound=getattr(self.config,a+('_max' if sign>0 else '_min'))
        if bound is None: return
        ppmm=getattr(self.config,a+'_ppmm')
        margin=self.jog_speed**2/(2*self.jog_accel)+self.jog_speed*.4+1
        predicted=self.status[a]+sign*margin
        if (sign>0 and predicted>=bound*ppmm) or (sign<0 and predicted<=bound*ppmm):
            raise ValueError('已接近软件边界的制动区域')

    def keep(self):
        if self.owner=='jog' and not self.releasing: self.lease_at=self.clock()

    def release(self):
        if self.owner!='jog' or self.releasing: return
        self.releasing=True; self.issue('JEND')

    def stop(self,reason='用户停止'):
        moving=self.owner is not None or bool(self.status and self.status['busy'])
        self.owner=None; self.steps=[]; self.active=None; self.wait_until=None; self.deadline=None
        self.stage='manual_idle'; self.releasing=False; self.error=reason
        if self.ready:
            self.issue('STOP')
            if self.status:
                self.status['armed']=0
                if moving: self.status['refx']=self.status['refz']=0
        self.notify('stopped',reason=reason)

    def packet(self,packet):
        kind=packet.get('type')
        if kind=='error': self.stop('控制器拒绝：'+str(packet.get('code'))); return
        if kind=='ack':
            cmd=packet.get('cmd')
            if cmd==self.pending:
                self.pending=None
                if cmd=='MOVE' and self.active: self.acked=True
            return
        if kind=='done':
            if self.active and self.acked: self.done=True
            return
        if kind!='status': return
        previous=self.status
        self.status=parse_status(dict(packet)); self.last_status=self.clock()
        recording_fault=(self.recording and (self.status['fault']!='NONE' or
            (previous and any(previous.get(k) and not self.status[k] for k in ('refx','refz')))))
        if recording_fault:
            self.stop('录制期间控制器故障或零点失效'); return
        if self.owner and (self.status['fault']!='NONE' or not self.status['armed'] or
                           not self.status['refx'] or not self.status['refz']):
            self.stop('控制器故障、取消使能或零点失效'); return
        if self.active and self.done and not self.status['busy']:
            if (self.status['x'],self.status['z'])!=(self.active.x,self.active.z):
                self.stop('完成位置与动作目标不一致'); return
            self.verified=True
        if self.owner=='jog' and self.releasing and self.pending is None and not self.status['busy']:
            self.owner=None; self.stage='manual_idle'; self.notify('jog_stopped')

    def tick(self):
        if not self.ready: return
        now=self.clock()
        if now-self.last_status>1.5:
            self.stop('超过 1.5 秒没有有效控制器状态'); self.ready=False; return
        if self.pending and now-self.pending_at>2:
            if self.pending=='STOP':
                self.pending=None; self.ready=False; self.notify('stopped',reason='STOP 未确认，连接失效')
            else: self.stop('指令确认超时')
            return
        if self.owner=='jog' and not self.releasing:
            if now-self.lease_at>.25: self.release(); return
            try: self.check_jog_boundary()
            except ValueError: self.release(); return
            if now-self.last_keep>=.1:
                self.send('JKEEP'); self.last_keep=now
        if self.active:
            if self.deadline is not None and now>self.deadline:
                self.stop('运动到位超时'); return
            if self.verified or (self.wait_until is not None and now>=self.wait_until):
                self.wait_until=None; self.step_pos+=1; self.advance()

    def snapshot(self):
        return dict(ready=self.ready,status=dict(self.status) if self.status else None,
                    pending=self.pending,owner=self.owner,stage=self.stage,error=self.error,
                    recording=self.recording,config=self.config.to_dict(),step=self.step_pos,
                    step_count=len(self.steps),idle=self.idle())
