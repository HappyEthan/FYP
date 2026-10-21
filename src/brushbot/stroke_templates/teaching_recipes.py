"""Authored curve seeds guided by disclosed tutorials, never captured motion."""
import copy


SOURCES = [
    dict(id='zhihu', title='硬笔书法28个基本笔画写法字帖教程',
         url='https://zhuanlan.zhihu.com/p/569336204',
         reading_url='https://www.zhihu.com/tardis/zm/art/569336204',
         medium='hard_pen', access='text_and_selected_illustrations',
         use='笔画分类、走向与阶段形态参考；不是毛笔运动记录', verified_at='2026-10-17'),
    dict(id='cn5v', title='楷书基本笔法十二例', url='https://www.cn5v.com/2020/03/14226.html',
         medium='brush', access='indexed_text_only_images_unverified',
         use='毛笔笔法的定性约束；原站配图尚未核验', verified_at='2026-10-17'),
]


def _part(name, phase, controls):
    return dict(id=name, phase=phase, controls=[[0, 0], *controls],
                adjustable_span=phase=='body' and name.split('_')[0] in ('horizontal','vertical','sweep','dot'))


def _event(name, part, t, label, action='travel', speed_hint='unspecified'):
    return dict(name=name, part=part, t=t, label=label, action=action, speed_hint=speed_hint)


def _recipe(identifier, name, stroke_type, variant, image, digest, url, parts, events, widths, rules, landmarks=()):
    return dict(id=identifier, name=name, type=stroke_type, variant=variant,
        illustration=dict(source_id='zhihu', filename=image, sha256=digest, url=url,
            role='hard_pen_structural_comparison_not_brush_motion_ground_truth',
            cumulative_stage_panels=True),
        parts=parts, events=events, width_knots=[dict(event=k, ratio=v) for k,v in widths],
        landmarks=list(landmarks), rule_notes=rules,
        numeric_parameter_basis='engineering_initial_values_not_measured_from_tutorial',
        construction='manually_authored_rule_based_curves')


def _pilot_strokes():
    common_events = lambda end: [_event('start','entry',0,'轻落起笔','touch_hint'),
        _event('body_start','entry',1,'转入行笔'),
        _event('body_end',end,1,'转入收笔','lift_hint'),
        _event('end','exit',1,'收笔结束','finish_hint')]
    strokes = [
        _recipe('dian_right','右点','dian','right_dot','zhihu_16.jpg',
            '465639f0cf0efe3c59c041e1e5333080d48fc27b46affd841404bd73b794b033',
            'https://pic4.zhimg.com/v2-7d3ccdff97725a72231f651dcc7ff801_1440w.jpg?consumer=ZHI_MENG',
            [_part('entry','entry',[[.08,-.06],[.24,-.15],[.35,-.28]]),
             _part('dot_body','body',[[.3,-.3],[.8,-.85],[.92,-1.45]]),
             _part('exit','exit',[[.10,-.10],[.15,-.21],[.12,-.26]])],
            common_events('dot_body'), [('start',.12),('body_start',.5),('body_end',1.1),('end',.7)],
            ['结构取右下行势，保留可见行笔长度。','轻起、逐步展开、末端收住；轻重只作定性意图。']),
        _recipe('hengzhegou','横折钩 · 短横长竖','hengzhegou','short_heng_long_shu','zhihu_30.jpg',
            'e88eba0d59a729d735c6256e4c10efaf754a22aee5cca83630e4de5b8be1d4bc',
            'https://pic3.zhimg.com/v2-076efaff04a5b46f1539ae32633d93e2_1440w.jpg?consumer=ZHI_MENG',
            [_part('entry','entry',[[.12,-.04],[.28,.02],[.5,.04]]),
             _part('horizontal','body',[[1.5,.08],[3.5,.35],[5,.4]]),
             _part('fold','body',[[.3,.04],[.4,-.30],[.35,-.75]]),
             _part('vertical','body',[[0,-3],[.05,-7],[-.15,-10]]),
             _part('hook_turn','body',[[-.10,-.8],[-.55,-1.1],[-.95,-.8]]),
             _part('exit','exit',[[-.35,.28],[-.8,.55],[-1.15,.85]])],
            [_event('start','entry',0,'起笔','touch_hint'),_event('body_start','entry',1,'横行'),
             _event('turn','fold',.5,'折转','press_hint','slower'),
             _event('hook','hook_turn',.5,'转钩','press_hint','slower'),
             _event('body_end','hook_turn',1,'出钩前调整','lift_hint'),
             _event('end','exit',1,'向左上出钩','finish_hint')],
            [('start',.15),('body_start',.55),('turn',1.05),('hook',1.2),('body_end',.7),('end',0)],
            ['横段与竖段分别控制长度，保持一笔连续。','横段相对细、竖段较饱满；钩前有圆转。',
             '长短比例与转折数值为人工初值，未宣称适合全部字。'], ['turn','hook']),
        _recipe('hengpie','横撇 · 短横弯撇','hengpie','short_heng_curved_pie','zhihu_31.jpg',
            'ea0328f9f48ef1991164f79a36618e99972da9c6c964c01d8e3e17db33a2a380',
            'https://pic3.zhimg.com/v2-5a172ec05c80db2ce8fd003846386e52_1440w.jpg?consumer=ZHI_MENG',
            [_part('entry','entry',[[.10,-.02],[.30,.01],[.5,.04]]),
             _part('horizontal','body',[[1.4,.1],[2.8,.45],[4,.55]]),
             _part('fold','body',[[.25,.06],[.28,-.25],[.08,-.6]]),
             _part('sweep','body',[[-.4,-1.9],[-2.2,-4.8],[-5.2,-7.4]]),
             _part('exit','exit',[[-.3,-.4],[-.7,-.7],[-1.2,-1.0]])],
            [_event('start','entry',0,'起笔','touch_hint'),_event('body_start','entry',1,'短横行笔'),
             _event('turn','fold',.5,'横撇折转','press_hint','slower'),
             _event('body_end','sweep',1,'提锋收撇','lift_hint'),_event('end','exit',1,'撇出尖','finish_hint')],
            [('start',.2),('body_start',.65),('turn',1.0),('body_end',.35),('end',0)],
            ['短横略向右上，折后向左下舒展。','横段与撇段可独立调整；收撇逐渐减小相对宽度。'], ['turn']),
        _recipe('pie_slant','斜撇','pie','slant','zhihu_11.jpg',
            '066b9ab88ba2b1c947758d5ac80c4653c0167b005c0c25f9d0c53a0560569177',
            'https://pic1.zhimg.com/v2-53b9435715abb8bc174f9b5c09360120_1440w.jpg?consumer=ZHI_MENG',
            [_part('entry','entry',[[.08,-.1],[.25,-.25],[.35,-.45]]),
             _part('sweep','body',[[.10,-1.2],[-3.4,-5],[-6,-6.8]]),
             _part('exit','exit',[[-.4,-.3],[-.8,-.55],[-1.3,-.85]])],
            common_events('sweep'), [('start',.4),('body_start',1),('body_end',.32),('end',0)],
            ['保持向左下的连续曲势。','前段较饱满，收尾渐细；弧度与长度为工程初值。']),
        _recipe('na_slant','斜捺','na','slant','zhihu_14.jpg',
            'd1b1f7036930d123b98f8eb102ee6ba131346633883c4eb7a6e0fb1ad31f5000',
            'https://pic4.zhimg.com/v2-30c04f06299ca730e084de8b0763b6c1_1440w.jpg?consumer=ZHI_MENG',
            [_part('entry','entry',[[.08,-.03],[.28,-.12],[.45,-.24]]),
             _part('sweep','body',[[1.4,-1.1],[4.2,-5.3],[7.3,-6.2]]),
             _part('foot','body',[[.8,-.45],[1.6,-.5],[2.3,-.2]]),
             _part('exit','exit',[[.8,.1],[1.4,.16],[2,.20]])],
            [_event('start','entry',0,'轻落起笔','touch_hint'),_event('body_start','entry',1,'向右下展开'),
             _event('foot','foot',.5,'捺脚转向','press_hint','slower'),
             _event('body_end','foot',1,'向右提锋','lift_hint'),_event('end','exit',1,'平出收尖','finish_hint')],
            [('start',.12),('body_start',.35),('foot',1.35),('body_end',.8),('end',0)],
            ['向右下展开后，在捺脚附近转向右方。','捺脚相对饱满，出锋渐细；宽度不代表力或磁目标。']),
    ]
    return strokes


def default_config():
    from .teaching_basics import additional_strokes, CATEGORIES
    strokes=_pilot_strokes()+additional_strokes()
    by_type={c['type']:c for c in CATEGORIES}
    for stroke in strokes:
        stroke['category']=copy.deepcopy(by_type[stroke['type']])
    strokes.sort(key=lambda r:r['category']['order'])
    return copy.deepcopy(dict(schema_version=1, role='teaching_stroke_recipes',
        style_id='kai_teaching_rules_v1', style_label='楷书教学规则重建', sources=SOURCES, strokes=strokes,
        note='覆盖参考教程28类，含独立写法变体。硬笔图只供结构参照；毛笔文字供定性规则。曲线与数值均为人工重建候选，待复核和实写验证。'))
