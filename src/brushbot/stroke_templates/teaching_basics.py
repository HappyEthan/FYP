"""Remaining basic strokes: authored local curves, with disclosed teaching assets.

Each numeric control is an engineering seed, not a traced or measured trajectory.
The small factories share entry/finish conventions; compound paths are authored
individually and retain every named turn, bend and hook.
"""
import json
from pathlib import Path

from .teaching_recipes import _event, _part, _recipe


CATEGORIES = [dict(order=i+1,type=kind,name=name) for i,(kind,name) in enumerate([
    ('heng','横'),('shu','竖'),('pie','撇'),('na','捺'),('dian','点'),('ti','提'),
    ('shugou','竖钩'),('wangou','弧弯钩'),('xiegou','戈钩（斜钩）'),('wogou','卧钩'),
    ('shuwan','竖弯'),('shuwangou','竖弯钩'),('shuti','竖提'),('henggou','横钩'),
    ('hengzhe','横折'),('hengzhegou','横折钩'),('hengpie','横撇'),('piezhe','撇折'),
    ('piedian','撇点'),('hengzhewangou','横折弯钩'),('shuzhe','竖折'),
    ('shuzhezhegou','竖折折钩'),('hengzheti','横折提'),('hengzhezhepie','横折折撇'),
    ('hengpiewangou','横撇弯钩'),('hengzhezhezhegou','横折折折钩'),
    ('hengzhewan','横折弯'),('shuzhepie','竖折撇')])]


def _p(name,controls,label=None):
    result=_part(name,'body',controls)
    if label:
        result['label']=label
    return result


def _eh():
    return _part('entry','entry',[[.1,-.03],[.3,.02],[.5,.04]])


def _ev():
    return _part('entry','entry',[[.08,-.08],[.23,-.24],[.25,-.45]])


def _ep():
    return _part('entry','entry',[[.05,-.08],[.18,-.28],[.2,-.45]])


def _exit(controls):
    return _part('exit','exit',controls)


def _round_h():
    return _exit([[.16,.02],[.4,-.04],[.5,-.15]])


def _round_v():
    return _exit([[.02,-.18],[.04,-.42],[.02,-.6]])


def _up_left():
    return _exit([[-.3,.25],[-.6,.5],[-.95,.8]])


def _up():
    return _exit([[.02,.25],[.02,.65],[-.02,1.]])


def _pie_end():
    return _exit([[-.25,-.25],[-.55,-.5],[-.9,-.75]])


def _ti_end():
    return _exit([[.25,.16],[.6,.4],[1.,.65]])


def _v(length=8.,name='vertical'):
    return _p(name,[[0,-length*.28],[.02,-length*.72],[0,-length]])


def _h(length=5.,rise=.4,name='horizontal'):
    return _p(name,[[length*.28,rise*.2],[length*.72,rise*.9],[length,rise]])


def _fold(name='fold'):
    return _p(name,[[.3,.02],[.36,-.2],[.3,-.65]])


def _left_fold(name='fold'):
    return _p(name,[[.25,.02],[.2,-.2],[-.15,-.5]])


def _right_fold(name='fold'):
    return _p(name,[[0,-.3],[.1,-.5],[.6,-.45]])


def _bend():
    return _p('bend',[[0,-.8],[.35,-1.2],[1.2,-1.2]])


def _hook_left():
    return _p('hook_turn',[[-.08,-.6],[-.3,-.85],[-.6,-.6]])


def _hook_up():
    return _p('hook_turn',[[.3,.02],[.45,.15],[.45,.45]])


def _feature(name,part,label,width=1.,action='press_hint',t=.5):
    return (name,part,t,label,width,action)


def _make(identifier,name,kind,variant,image,parts,rules,features=(),width=(.4,.9,.55,0),body_speed='unspecified'):
    asset=json.loads(Path(__file__).with_name('teaching_assets.json').read_text())[str(image)]
    events=[_event('start','entry',0,'起笔','touch_hint'),
            _event('body_start','entry',1,'转入行笔',speed_hint=body_speed)]
    knots=[('start',width[0]),('body_start',width[1])]
    for key,part,t,label,ratio,action in features:
        events.append(_event(key,part,t,label,action,'slower' if action=='press_hint' else 'unspecified'))
        knots.append((key,ratio))
    events.extend([_event('body_end',parts[-2]['id'],1,'转入收笔',
                         'lift_hint' if width[-1]==0 else 'press_hint'),
                   _event('end','exit',1,'出锋结束' if width[-1]==0 else '收住结束','finish_hint')])
    knots.extend([('body_end',width[2]),('end',width[3])])
    return _recipe(identifier,name,kind,variant,asset['filename'],asset['sha256'],asset['url'],
                   parts,events,knots,rules,[f[0] for f in features])


def additional_strokes():
    return [
        _make('heng_long','长横','heng','long',6,
            [_eh(),_p('horizontal',[[3.5,.32],[8.5,.95],[12,.6]]),_round_h()],
            ['左低右高，主体保留轻微弧势。','起收相对饱满，行笔相对细；长横单独建模。'],width=(.5,.9,.65,1.05)),
        _make('heng_short','短横','heng','short',7,
            [_eh(),_h(5,.5),_round_h()],
            ['短横较紧凑，右端略高。','轻起后逐渐展开，末端收住。'],width=(.18,.45,.85,.95)),
        _make('shu_chuilu','垂露竖','shu','chuilu',8,
            [_ev(),_v(10),_round_v()],['竖向主体保持挺直。','末端保留饱满收势。'],width=(.55,1,.7,1.)),
        _make('shu_xuanzhen','悬针竖','shu','xuanzhen',9,
            [_ev(),_v(9),_exit([[0,-.4],[0,-1.2],[0,-2.]])],
            ['前段保持竖向，末段延续方向。','渐提收尖，与垂露的收住形态分别保存。'],width=(.55,1,.65,0)),
        _make('shu_short','短竖','shu','short',10,
            [_ev(),_v(4),_round_v()],['短竖以紧凑竖势为主。','用独立宽度意图区分短粗与长竖。'],width=(.5,1.05,.8,1.05)),
        _make('pie_vertical','竖撇','pie','vertical',12,
            [_ep(),_v(5.6),_p('bend',[[0,-.4],[-.1,-.7],[-.25,-1.]]),
             _p('sweep',[[-.3,-1],[-.9,-2.5],[-1.8,-3.5]]),_pie_end()],
            ['先以竖势行笔，后段逐步向左下转出。','弯转与撇尾分别保留，末端收尖。'],
            [_feature('curve','bend','由竖转撇',.75,'lift_hint')]),
        _make('pie_short_flat','短撇 · 平势','pie','short_flat',13,
            [_ep(),_p('sweep',[[-.6,-.2],[-2,-.7],[-3.8,-1.3]]),_exit([[-.2,-.07],[-.45,-.16],[-.7,-.25]])],
            ['用于字头时取较平的左下行势，依据教程正文描述。','配图为短撇通用对照；平势角度为人工初值，收尾渐细。']),
        _make('pie_short_slant','短撇 · 斜势','pie','short_slant',13,
            [_ep(),_p('sweep',[[-.1,-.6],[-1.2,-2],[-2,-2.8]]),_pie_end()],
            ['左上部位可采用较陡的短撇。','主体紧凑，收尾向左下出锋。']),
        _make('na_flat','平捺','na','flat',15,
            [_eh(),_p('horizontal',[[1.5,.08],[2.2,.05],[2.8,-.15]]),
             _p('sweep',[[1.5,-.2],[4.5,-1.8],[6.3,-2.2]]),
             _p('foot',[[.8,-.2],[1.5,-.25],[2,-.12]]),_exit([[.6,0],[1.1,.02],[1.7,.05]])],
            ['先有短横过渡，再向较平的右下方向展开。','捺脚转向右方，末端渐提出尖。'],
            [_feature('curve','sweep','短横转入平捺',.6,'travel',t=0),
             _feature('foot','foot','捺脚转向',1.35)],width=(.12,.35,.8,0)),
        _make('dian_left','左点','dian','left_dot',17,
            [_part('entry','entry',[[.02,-.15],[-.04,-.3],[-.1,-.4]]),
             _p('dot_body',[[-.12,-.35],[-.4,-.9],[-.5,-1.3]]),_exit([[-.05,-.1],[0,-.21],[.06,-.25]])],
            ['行笔朝下并略向左。','点画保留行程，末端收住。'],width=(.12,.5,1.1,.8)),
        _make('dian_vertical','竖点','dian','vertical_dot',18,
            [_part('entry','entry',[[.08,-.1],[.15,-.2],[.16,-.35]]),
             _p('dot_body',[[-.01,-.45],[.04,-1],[.02,-1.5]]),_exit([[0,-.12],[-.02,-.3],[-.04,-.38]])],
            ['以较直的向下行势展开。','独立保留点的长度与收笔，不混作完整竖画。'],width=(.12,.5,1.05,.8)),
        _make('dian_long','长点','dian','long_dot',19,
            [_part('entry','entry',[[.08,-.04],[.25,-.12],[.35,-.25]]),
             _p('dot_body',[[.5,-.2],[1.8,-1],[3.2,-1.9]]),_exit([[.2,-.12],[.4,-.25],[.48,-.42]])],
            ['右下行势比右点舒展。','行笔给出相对放慢提示，末端仍收住。'],width=(.12,.4,1.1,.9),body_speed='slower'),
        _make('ti','提','ti','standard',20,
            [_part('entry','entry',[[.1,-.05],[.26,.02],[.42,.14]]),
             _p('sweep',[[1.2,.45],[3,1.6],[4.6,2.8]]),_ti_end()],
            ['从左下向右上提行。','前段相对饱满，向尖端逐步减小宽度意图。'],width=(.7,1,.35,0)),
        _make('shugou','竖钩','shugou','standard',21,
            [_ev(),_v(10),_hook_left(),_up_left()],
            ['先行竖势，钩前保留局部调整段。','钩朝左上，出锋段短于主体。'],[_feature('hook','hook_turn','转钩',1.15)]),
        _make('wangou','弧弯钩','wangou','standard',22,
            [_ev(),_p('sweep',[[2,-2.7],[2,-7],[.25,-9.4]]),_hook_left(),_up_left()],
            ['主体向右鼓出弧势，起钩处回到起笔附近的竖向范围。','钩前调整后向左上出锋。'],
            [_feature('bow','sweep','弧势中段',.9,'travel'),_feature('hook','hook_turn','转钩',1.1)],width=(.18,.6,.6,0)),
        _make('xiegou','戈钩（斜钩）','xiegou','standard',23,
            [_ev(),_p('sweep',[[0,-2.5],[2,-6.4],[4.6,-8.8]]),
             _p('hook_turn',[[.3,-.55],[.55,-.6],[.65,-.25]]),_up()],
            ['右下行势保持有弧度的斜势。','末端转为向上出钩，区别于左上出钩。'],[_feature('hook','hook_turn','向上转钩',1.1)]),
        _make('wogou','卧钩','wogou','standard',24,
            [_part('entry','entry',[[.1,-.12],[.25,-.4],[.4,-.65]]),
             _p('sweep',[[1.3,-2],[4.6,-2.5],[7,-1.5]]),
             _p('hook_turn',[[.45,.12],[.75,.25],[.5,.6]]),_exit([[-.25,.4],[-.6,.9],[-1,1.3]])],
            ['先向右下，再逐渐圆转向右。','末端向左上出钩，钩不夸大。'],
            [_feature('curve','sweep','圆转行笔',.9,'lift_hint'),_feature('hook','hook_turn','转钩',1.1)],width=(.18,.65,.6,0)),
        _make('shuwan','竖弯','shuwan','standard',25,
            [_ev(),_v(4),_bend(),_h(3.5,.1),_round_h()],
            ['短竖后以圆弯过渡到右行。','末端收住，弯处保持圆转。'],[_feature('curve','bend','圆弯',.75,'lift_hint')],width=(.45,.9,.7,1.)),
        _make('shuwangou','竖弯钩','shuwangou','standard',26,
            [_ev(),_v(8),_bend(),_h(5,.4),_hook_up(),_up()],
            ['竖段后圆转右行，末端再向上出钩。','圆弯与起钩分别标记，横竖长度可分别调整。'],
            [_feature('curve','bend','圆弯',.75,'lift_hint'),_feature('hook','hook_turn','向上转钩',1.1)]),
        _make('shuti','竖提','shuti','standard',27,
            [_ev(),_v(8),_p('fold',[[0,-.4],[.1,-.6],[.35,-.4]]),
             _p('sweep',[[.7,.3],[2,1],[2.8,1.7]]),_ti_end()],
            ['先竖后转向右上斜提。','转折处保留调整位置，提尾收尖。'],[_feature('turn','fold','竖转提',1.)]),
        _make('henggou','横钩','henggou','standard',28,
            [_eh(),_h(10,.7),_p('hook_turn',[[.45,.03],[.55,-.12],[.3,-.45]]),
             _exit([[-.3,-.25],[-.6,-.5],[-1,-.8]])],
            ['横行后局部转钩。','钩朝左下，宽度意图逐步收到尖端。'],[_feature('hook','hook_turn','向左下转钩',1.1)]),
        _make('hengzhe','横折','hengzhe','standard',29,
            [_eh(),_h(7,.6),_fold(),_p('vertical',[[0,-2],[-.2,-4],[-.3,-6]]),_round_v()],
            ['横行转向下行，整笔保持连续。','折处为小范围转向，避免夸大的双角。'],[_feature('turn','fold','横转竖',1.1)],width=(.4,.75,.75,.95)),
        _make('piezhe','撇折','piezhe','standard',32,
            [_ep(),_p('sweep',[[-.4,-1],[-1.7,-3.4],[-3,-5]]),
             _p('fold',[[-.2,-.25],[-.3,-.4],[.1,-.32]]),
             _p('sweep_2',[[1.1,.35],[3,.95],[5,1.9]],'提段'),_ti_end()],
            ['先向左下撇行，再转向右上。','转折处不断笔，末段按提势出尖。'],[_feature('turn','fold','撇转提',1.)]),
        _make('piedian','撇点','piedian','standard',33,
            [_ep(),_p('sweep',[[-.3,-1],[-1.4,-3.8],[-3,-5]]),
             _p('fold',[[-.2,-.2],[-.1,-.35],[.3,-.4]]),
             _p('sweep_2',[[1.8,-.35],[4,-1.6],[5,-3]],'长点段'),_exit([[.1,-.12],[.23,-.25],[.3,-.35]])],
            ['撇段与右下长点连续相接。','中间不作出尖收笔，末端收住。'],[_feature('turn','fold','撇转长点',.9)],width=(.4,.9,1.1,.9)),
        _make('hengzhewangou','横折弯钩','hengzhewangou','standard',34,
            [_eh(),_h(),_fold(),_p('vertical',[[0,-1],[-.25,-3],[-.45,-4.7]]),
             _bend(),_h(5,.4,'horizontal_2'),_hook_up(),_up()],
            ['横折向下后，以圆弯接下部右行。','折、圆弯和向上出钩分别保存。'],
            [_feature('turn','fold','横折',1.05),_feature('curve','bend','下部圆弯',.75,'lift_hint'),
             _feature('hook','hook_turn','向上转钩',1.1)]),
        _make('shuzhe','竖折','shuzhe','standard',35,
            [_ev(),_v(6),_right_fold(),_h(6,.3),_round_h()],
            ['竖势转为向右横行。','紧凑折转与竖弯的圆弯分别建模，收笔保留重量意图。'],
            [_feature('turn','fold','竖转横',1.05)],width=(.4,.9,.75,1.)),
        _make('shuzhezhegou','竖折折钩','shuzhezhegou','standard',36,
            [_ep(),_p('vertical',[[-.25,-1],[-.4,-2.2],[-.6,-3]]),_right_fold(),
             _h(5,.3),_fold('fold_2'),_p('vertical_2',[[-.1,-1.5],[-.5,-4],[-1,-5.8]],'第二竖段'),
             _hook_left(),_up_left()],
            ['短竖折右横，再折为略倾的下行钩段。','两处折转和钩各自独立，避免拉伸时合并特征。'],
            [_feature('turn_1','fold','第一折',1.),_feature('turn_2','fold_2','第二折',1.05),
             _feature('hook','hook_turn','转钩',1.1)]),
        _make('hengzheti','横折提','hengzheti','standard',37,
            [_eh(),_h(4,.4),_fold(),_v(7),_p('fold_2',[[0,-.3],[.1,-.5],[.35,-.32]]),
             _p('sweep',[[.7,.35],[1.4,.8],[2,1.25]]),_ti_end()],
            ['短横折下行，再转向右上提行。','提段较短，末端收尖。'],
            [_feature('turn_1','fold','横转竖',1.),_feature('turn_2','fold_2','竖转提',1.)]),
        _make('hengzhezhepie','横折折撇','hengzhezhepie','standard',38,
            [_eh(),_h(4.5,.6),_left_fold(),_p('sweep',[[-.7,-.7],[-1.4,-1.7],[-2.3,-2.4]]),
             _p('fold_2',[[-.2,-.2],[-.15,-.25],[.3,-.2]]),_h(3,.7,'horizontal_2'),
             _left_fold('fold_3'),_p('sweep_2',[[-.2,-1.8],[-1.8,-4.2],[-4,-5.4]],'末撇段'),_pie_end()],
            ['横、短撇、小横、末撇顺次连接。','中间短撇不收尖，最后一撇才完成出锋。'],
            [_feature('turn_1','fold','第一折',1.),_feature('turn_2','fold_2','第二折',.95),
             _feature('turn_3','fold_3','折入末撇',1.)]),
        _make('hengpiewangou','横撇弯钩','hengpiewangou','standard',39,
            [_eh(),_h(4,.4),_left_fold(),_p('sweep',[[-.3,-.8],[-1.2,-2],[-1.8,-2.8]]),
             _p('bend',[[-.1,-.25],[.5,-.4],[.9,-1]]),
             _p('sweep_2',[[1.2,-1.2],[1.1,-3.1],[-.2,-3.6]],'弯钩主体'),_hook_left(),_up_left()],
            ['短横转短撇后，继续圆转写弯钩。','整笔连续，折、圆弯、出钩分别标记。'],
            [_feature('turn','fold','横转撇',1.),_feature('curve','bend','接入弯钩',.75,'lift_hint'),
             _feature('hook','hook_turn','转钩',1.1)]),
        _make('hengzhezhezhegou','横折折折钩','hengzhezhezhegou','standard',40,
            [_eh(),_h(4.5,.6),_left_fold(),_p('sweep',[[-.5,-.6],[-1.2,-1.5],[-2.1,-2.3]]),
             _p('fold_2',[[-.1,-.15],[.05,-.25],[.4,-.15]]),_h(3.2,.5,'horizontal_2'),
             _fold('fold_3'),_p('sweep_2',[[-.1,-2],[-.7,-4],[-1.8,-5.4]],'末钩主体'),
             _hook_left(),_up_left()],
            ['短横、短撇、第二横、下行弯钩分段连接。','三处折转和末钩独立，第二横可单独改变长度。'],
            [_feature('turn_1','fold','第一折',1.),_feature('turn_2','fold_2','第二折',.95),
             _feature('turn_3','fold_3','第三折',1.05),_feature('hook','hook_turn','转钩',1.1)]),
        _make('hengzhewan','横折弯','hengzhewan','standard',41,
            [_eh(),_h(4.5,.4),_fold(),_v(5),_bend(),_h(4,.2,'horizontal_2'),_round_h()],
            ['横折接短竖，再圆弯向右收住。','末端保留收势，不增加向上的钩。'],
            [_feature('turn','fold','横折',1.),_feature('curve','bend','下部圆弯',.75,'lift_hint')],width=(.4,.8,.7,1.)),
        _make('shuzhepie','竖折撇','shuzhepie','standard',42,
            [_part('entry','entry',[[-.1,-.1],[-.2,-.3],[-.25,-.5]]),
             _p('vertical',[[-.25,-1],[-.6,-2.9],[-.9,-4.2]]),_right_fold(),_h(4,.5),
             _left_fold('fold_2'),_p('sweep',[[-.3,-1.2],[-1.7,-3.7],[-3.8,-5.1]]),_pie_end()],
            ['略斜的竖势折右横，再折向左下撇出。','两折分别保留，最终以撇尾收尖。'],
            [_feature('turn_1','fold','竖转横',1.),_feature('turn_2','fold_2','横转撇',1.)]),
    ]
