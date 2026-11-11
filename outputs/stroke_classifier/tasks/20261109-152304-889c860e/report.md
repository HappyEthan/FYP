# 磁响应笔画训练结果

实验：10次；笔画：70笔

整次实验留一验证；新实验测试另存。

|模型|总错分|最差类别召回率|最差实验正确数|推荐顺序|
|---|---:|---:|---:|---:|
|幅值模型|2/70|90.0%|6/7|4|
|方向模型|1/70|90.0%|6/7|1|
|特征融合|1/70|90.0%|6/7|1|
|分数融合|1/70|90.0%|6/7|1|
|形状／变化率融合|2/70|90.0%|6/7|4|

## 分支状态

{
  "F0": {
    "status": "completed",
    "model_id": "88a3290529c1"
  },
  "F1": {
    "status": "completed",
    "model_id": "e456b31d081a"
  },
  "F2": {
    "status": "completed",
    "model_id": "133ec44d597c"
  },
  "F3": {
    "status": "completed",
    "model_id": "800ea7249f06"
  },
  "F4": {
    "status": "completed",
    "model_id": "5f2fc857fc6d"
  }
}

## 条件项

{
  "A3": "未提供独立共同参考响应／增益证据，条件不足",
  "direction_variants": {
    "available": [
      "D1",
      "D2",
      "D3"
    ],
    "unavailable": []
  },
  "reference": "每笔前10%原生EMA中位数扣除；不是接触前空载参考",
  "robustness": "数学偏移／相对旋转对照",
  "auxiliary_LinearSVC": "未执行辅助实现对照；不影响F0—F4主模型定义",
  "position_majority_controls": "顺序不用作特征；完整七类每类一次，多数类正确率1/7，顺序映射为非磁识别对照",
  "scope": "本次选中模型和候选范围；不声称所有研究扩展分支全部完成"
}