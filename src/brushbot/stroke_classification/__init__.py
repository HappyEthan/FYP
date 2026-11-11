"""Offline magnetic stroke classification. Does not import robot services."""

LABELS = ('右点', '横折钩', '横撇', '撇', '捺', '横', '竖')
VERSION = 'magnetic-seven-stroke-v1'
FAMILIES = {'F0':'幅值模型', 'F1':'方向模型', 'F2':'特征融合',
            'F3':'分数融合', 'F4':'形状／变化率融合'}
