# 随机变化窗口阻塞排查与修复（2026-11-09）

## 现象与根因

用户报告点击“生成本次变化”后 Python 窗口卡死。原调用链为 `VariationDialog.generate → preview → PathModel.compile_workspace`，在 Qt GUI 主线程同步执行全部笔画的标准编译、随机版本编译及自动适速。按钮返回前，事件循环不能处理重绘和输入。

当前 `outputs/brush_path_editor/draft_v3.json` 包含七笔。离线复现中，种子 101 的随机场生成约 0.191 秒，编译约 11.091 秒，计算最终完成，本次未观察到死循环或线程死锁。对草稿已有随机批次作性能分析（分析器本身增加耗时），记录到 276 次内部 compile_recipe 调用，耗时主要来自自动适速迭代及重复编译。外层最多 11 轮缩幅、内层最多 160 轮适速，使复杂路径可能长时间计算。

原窗口打开已有随机批次时也会同步预检；应用时先清空结果再预检，会再次调用完整编译入口。

## 修复

- 随机窗口使用 QThread 在独立模型副本上编译；只有 GUI 线程更新控件和采用结果。
- 打开已有结果时延迟启动后台预检，窗口构造不再同步编译。
- 计算期间禁用生成、预检、参数编辑和应用，防止重复提交；取消仍可用。
- 取消立即关闭窗口，向后台发出中断请求；随机缩幅及自动适速循环增加协作式取消检查。
- 取消的结果不会应用到主编辑器；工作线程保留到结束，避免运行中析构 QThread。
- 已完成且参数未变的预览直接应用，不再先清空再重复编译。
- 随机算法、前馈表范围、运动限制和原有预检保持不变。未执行机械臂运动，未改写当前草稿。

修改文件：`scripts/brush_variation_dialog.py`、`scripts/brush_path_variation.py`、`scripts/brush_speed_adaptation.py`、`src/brushbot/planning.py`。

## 验证

修复前新增两项回归测试，分别失败于“计算阻塞 GUI 事件循环”和“应用再次调用编译”。修复后通过，并补充取消与错误恢复覆盖；原 UI 测试改为等待异步结果。

专项命令：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=.:src .venv/bin/python -m pytest tests/test_brush_variation_responsiveness.py tests/test_brush_variation_ui.py tests/test_brush_variation_model.py tests/test_stroke_variation.py tests/test_strokeplan_variation_targets.py tests/test_variation_bundle.py -q
```

结果：49 passed in 6.84s。

当前七笔草稿 Qt offscreen 端到端测试：生成按钮处理约 0.284 秒返回；完整预检约 11.902 秒；25 ms 定时器期间触发 442 次，最大触发间隔约 0.140 秒；预检成功，草稿 SHA-256 未改变。计算仍需时间，后台执行解决的是界面长时间无法响应。

同一草稿取消测试：取消处理约 0.000039 秒返回，后台线程约 0.103 秒停止，结果未应用。取消为协作式，响应时间取决于到达下一个检查点，并非任意函数内强制终止。

独立检查：自动适速在取消上下文中抛出 PlanningCancelled；退出上下文后常规预检正常通过。

全仓命令：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=.:src .venv/bin/python -m pytest
```

结果：69 failed, 1404 passed, 7 skipped in 115.89s。以下 69 个失败名称均已列在 `2026-11-06-随机变化功能验证记录.md` 的历史失败记录中。本次未修复这些其他模块的问题，也没有将全仓报告为通过。原始完整日志：`/tmp/fyp-variation-freeze-pytest.log`。

## 全仓失败项目

- `tests/test_calligraphy_trial.py::test_zhong_preserves_stroke_order_shape_and_target_only_provenance`
- `tests/test_calligraphy_trial.py::test_trial_exports_same_paper_coordinates_for_each_independent_stroke`
- `tests/test_calligraphy_trial.py::test_zhong_runner_defaults_to_offline_pi_for_selected_stroke`
- `tests/test_calligraphy_trial.py::test_omitting_stroke_preflights_all_four_without_confirmation`
- `tests/test_calligraphy_trial.py::test_character_confirmation_order_and_stop_on_failure[RUN-None-expected0]`
- `tests/test_calligraphy_trial.py::test_character_confirmation_order_and_stop_on_failure[RUN-2-expected1]`
- `tests/test_calligraphy_trial.py::test_character_confirmation_order_and_stop_on_failure[cancel-None-expected2]`
- `tests/test_calligraphy_trial.py::test_invalid_last_stroke_blocks_whole_character_before_confirmation`
- `tests/test_calligraphy_trial.py::test_edited_character_stroke_rejects_invalid_selection[0]`
- `tests/test_calligraphy_trial.py::test_edited_character_stroke_rejects_invalid_selection[5]`
- `tests/test_character_library_browser.py::test_character_library_defaults_to_compositions_in_practice_order_without_removing_history`
- `tests/test_contact_entry_test.py::test_completed_fake_run_records_vectors_and_metrics`
- `tests/test_contact_entry_test.py::test_servo_restart_latency_is_excluded_from_contact_timeline`
- `tests/test_contact_entry_test.py::test_recorded_contact_driver_does_not_catch_up_in_a_command_burst[0.0]`
- `tests/test_contact_entry_test.py::test_recorded_contact_driver_does_not_catch_up_in_a_command_burst[0.002]`
- `tests/test_contact_entry_test.py::test_contact_continues_after_160_ms_stall_above_z20`
- `tests/test_exhibition_api.py::test_preview_rejects_multiple_characters_and_returns_strokes_for_one`
- `tests/test_exhibition_preview.py::test_preview_contains_single_character_strokes`
- `tests/test_exhibition_preview.py::test_plan_builder_returns_fixed_six_dimensional_waypoints`
- `tests/test_four_direction_sweep.py::test_execution_rebaselines_in_direction_and_records_no_feedback`
- `tests/test_four_direction_sweep.py::test_constant_height_no_return_run_keeps_direction_baseline`
- `tests/test_four_direction_sweep.py::test_successful_sensor_reboot_is_saved_with_each_trial_baselines`
- `tests/test_four_direction_sweep.py::test_baseline_recovers_after_startup_outlier_without_dropping_raw_data[BASELINE]`
- `tests/test_four_direction_sweep.py::test_baseline_recovers_after_startup_outlier_without_dropping_raw_data[REBASELINE]`
- `tests/test_four_direction_sweep.py::test_bz_variation_is_recorded_but_does_not_gate_xy_baseline`
- `tests/test_record_hanzi_openloop.py::test_yong_waypoints_are_multi_stroke_and_safe`
- `tests/test_record_hanzi_openloop.py::test_actual_tcp_is_first_pose_for_continuous_entry`
- `tests/test_record_hanzi_openloop.py::test_initial_xy_move_stays_at_wait_height`
- `tests/test_run_ladder_experiment.py::test_runner_prompts_after_passes_four_eight_and_twelve`
- `tests/test_run_ladder_experiment.py::test_runner_prompts_to_wet_and_rebaselines_between_every_path`
- `tests/test_run_ladder_experiment.py::test_runner_automatically_rebaselines_after_each_wetting_cycle`
- `tests/test_short_plateau_pi_experiment.py::test_pi_records_state_only_during_measurement`
- `tests/test_stroke_template_catalog.py::test_practice_order_keeps_latest_unlisted_character_before_its_partial_draft`
- `tests/test_stroke_template_catalog_browser.py::test_catalog_search_versions_and_links_work_offline`
- `tests/test_stroke_template_examples.py::test_demo_publishes_simple_characters_and_length_transfer_without_validation_claim`
- `tests/test_strokeplan_rotational_entry.py::test_recorded_rotation_and_p_only_during_measurement[feedforward]`
- `tests/test_strokeplan_rotational_entry.py::test_recorded_rotation_and_p_only_during_measurement[p]`
- `tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[late_tick-feedforward]`
- `tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[late_tick-p]`
- `tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[repeated_poll-feedforward]`
- `tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[repeated_poll-p]`
- `tests/test_strokeplan_stationary_entry.py::test_stationary_pi_records_whole_curve_and_resets_at_lift`
- `tests/test_teaching_stroke_distribution.py::test_built_wheel_can_load_all_recipes_without_the_source_checkout`
- `tests/test_template_character_composition.py::test_cli_composes_yong_from_library_and_rebuilds_from_its_self_contained_recipe`
- `tests/test_template_character_composition.py::test_parameter_changes_affect_only_the_chosen_stroke`
- `tests/test_template_character_composition.py::test_explicit_reference_ink_constraint_rejects_in_canvas_but_misaligned_paths`
- `tests/test_template_character_composition.py::test_rebuilding_an_old_character_cannot_promote_its_template_snapshots_over_newer_library_models`
- `tests/test_template_character_composition.py::test_composition_rejects_template_files_not_bound_by_the_manifest[template.json]`
- `tests/test_template_character_composition.py::test_composition_rejects_template_files_not_bound_by_the_manifest[report.html]`
- `tests/test_template_character_composition.py::test_composition_can_reuse_one_versioned_model_for_two_strokes`
- `tests/test_template_character_composition.py::test_bad_composition_inputs_cannot_publish_an_incomplete_character[template_id]`
- `tests/test_template_character_composition.py::test_bad_composition_inputs_cannot_publish_an_incomplete_character[layout_id]`
- `tests/test_template_character_composition.py::test_bad_composition_inputs_cannot_publish_an_incomplete_character[missing_stroke]`
- `tests/test_template_character_composition.py::test_bad_composition_inputs_cannot_publish_an_incomplete_character[unknown_parameter]`
- `tests/test_template_composition_browser.py::test_latest_yong_opens_as_template_composition_with_layout_toggle_and_source_links`
- `tests/test_yong_quick_browser.py::test_local_drag_undo_and_direct_exports_preserve_the_other_four_strokes`
- `tests/test_yong_quick_browser.py::test_advanced_yong_edits_keep_named_features_on_the_same_points`
- `tests/test_yong_quick_review.py::test_yong_has_five_named_strokes_and_explicit_turn_hook_landmarks`
- `tests/test_yong_quick_review.py::test_all_five_yong_templates_build_and_fit_without_user_phase_editing`
- `tests/test_yong_quick_review.py::test_manual_preserve_mode_keeps_all_points_exactly_even_without_a_template`
- `tests/test_yong_quick_review.py::test_yong_cli_publishes_a_direct_quick_review_entry`
- `tests/test_yong_quick_review.py::test_incompatible_yong_dictionary_hint_is_an_actionable_error[truncate]`
- `tests/test_yong_quick_review.py::test_incompatible_yong_dictionary_hint_is_an_actionable_error[insert_same_polyline_vertex]`
- `tests/test_z_identification.py::test_sweep_recording_and_analysis_preserve_directions_without_fitting_delay[sweep-down]`
- `tests/test_z_identification.py::test_sweep_recording_and_analysis_preserve_directions_without_fitting_delay[sweep-cycle]`
- `tests/test_z_identification.py::test_full_run_records_null_targets_segments_and_one_airborne_baseline`
- `tests/test_z_identification.py::test_analysis_exports_quality_flags_and_preserves_raw_input`
- `tests/test_z_identification.py::test_analysis_retains_completed_run_with_timing_quality_flags[skipped]`
- `tests/test_z_identification.py::test_analysis_retains_completed_run_with_timing_quality_flags[balanced_duplicate]`
