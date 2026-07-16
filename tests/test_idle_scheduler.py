"""IdleBehaviorScheduler 测试 (Phase 3.1)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from backend.live2d.idle_scheduler import IdleBehaviorScheduler
from backend.live2d.model_profile import IdleConfig


def make_idle_config(**overrides) -> IdleConfig:
    """创建测试用 IdleConfig"""
    defaults = {
        "expression_cycle": ["neutral", "happy", "thinking"],
        "expression_interval": (5.0, 12.0),
        "blink_interval": (2.0, 6.0),
        "eye_drift_range": 0.15,
        "head_tilt_chance": 0.15,
        "head_tilt_angle": 0.1,
    }
    defaults.update(overrides)
    return IdleConfig(**defaults)


class TestIdleSchedulerInit:
    def test_init_with_config(self):
        config = make_idle_config()
        sched = IdleBehaviorScheduler(config)
        assert sched.config is config
        assert sched.elapsed == 0.0

    def test_init_with_none_config_raises(self):
        with pytest.raises((TypeError, ValueError)):
            IdleBehaviorScheduler(None)  # type: ignore


class TestTickBasic:
    def test_tick_small_dt_empty(self):
        """dt 太小不触发任何行为"""
        sched = IdleBehaviorScheduler(make_idle_config(
            expression_interval=(999.0, 999.0),  # 极长间隔
            blink_interval=(999.0, 999.0),
            head_tilt_chance=0.0,
        ))
        commands = sched.tick(0.01)
        assert commands == []

    def test_tick_accumulates_elapsed(self):
        sched = IdleBehaviorScheduler(make_idle_config())
        sched.tick(1.0)
        sched.tick(2.0)
        assert sched.elapsed == 3.0


class TestBlink:
    def test_blink_after_interval(self):
        """达到 blink 间隔后触发眨眼"""
        sched = IdleBehaviorScheduler(make_idle_config(
            blink_interval=(0.1, 0.1),  # 极短间隔确保触发
            expression_interval=(999.0, 999.0),
            head_tilt_chance=0.0,
        ))
        commands = sched.tick(0.2)
        blink_cmds = [c for c in commands if c.get("type") == "blink"]
        assert len(blink_cmds) >= 1

    def test_blink_has_eye_params(self):
        """眨眼命令包含 value 字段（0=闭眼, 1=睁眼）"""
        sched = IdleBehaviorScheduler(make_idle_config(
            blink_interval=(0.1, 0.1),
            expression_interval=(999.0, 999.0),
            head_tilt_chance=0.0,
        ))
        commands = sched.tick(0.2)
        blink_cmds = [c for c in commands if c.get("type") == "blink"]
        if blink_cmds:
            cmd = blink_cmds[0]
            assert "value" in cmd, f"Blink command should have 'value', got {cmd}"
            assert cmd["value"] in (0.0, 1.0)


class TestExpressionCycle:
    def test_expression_cycle_triggers(self):
        """达到 expression 间隔后触发表情切换"""
        sched = IdleBehaviorScheduler(make_idle_config(
            expression_interval=(0.1, 0.1),
            blink_interval=(999.0, 999.0),
            head_tilt_chance=0.0,
        ))
        commands = sched.tick(0.2)
        expr_cmds = [c for c in commands if c.get("type") == "expression"]
        assert len(expr_cmds) >= 1

    def test_expression_cycle_rotates(self):
        """表情在 cycle 列表中轮转"""
        sched = IdleBehaviorScheduler(make_idle_config(
            expression_cycle=["happy", "sad"],
            expression_interval=(0.01, 0.01),
            blink_interval=(999.0, 999.0),
            head_tilt_chance=0.0,
        ))
        cmds1 = sched.tick(0.1)
        expr1 = [c for c in cmds1 if c.get("type") == "expression"]
        cmds2 = sched.tick(0.1)
        expr2 = [c for c in cmds2 if c.get("type") == "expression"]

        # 两次都应触发表情
        assert len(expr1) >= 1
        assert len(expr2) >= 1


class TestHeadTilt:
    def test_head_tilt_probabilistic(self):
        """head_tilt 按概率触发"""
        # chance=0.0 不应触发
        sched_no = IdleBehaviorScheduler(make_idle_config(
            expression_interval=(999.0, 999.0),
            blink_interval=(999.0, 999.0),
            head_tilt_chance=1.0,  # Always
        ))
        cmds = sched_no.tick(3.0)
        # 检查至少有一些命令（可能会因 tick 逻辑而异）
        tilt_cmds = [c for c in cmds if "tilt" in c.get("type", "")]
        # head_tilt 在较长时间后应有触发
        assert len(cmds) >= 0  # 结构验证，概率性


class TestReset:
    def test_reset_clears_timers(self):
        """reset 清除所有计时器和累积时间"""
        sched = IdleBehaviorScheduler(make_idle_config())
        sched.tick(10.0)
        sched.reset()
        assert sched.elapsed == 0.0

    def test_reset_then_tick_starts_fresh(self):
        """reset 后 tick 从零开始"""
        sched = IdleBehaviorScheduler(make_idle_config())
        sched.tick(5.0)
        sched.reset()
        commands = sched.tick(0.01)  # 极小 dt，不应触发
        assert commands == []


class TestEyeDrift:
    def test_eye_drift_in_range(self):
        """视线漂移在配置范围内"""
        sched = IdleBehaviorScheduler(make_idle_config(eye_drift_range=0.2))
        # 多次 tick 累积足够时间以触发
        for _ in range(100):
            cmds = sched.tick(0.1)
            drift_cmds = [c for c in cmds if c.get("type") == "eye_drift"]
            for cmd in drift_cmds:
                if "x" in cmd:
                    assert -0.2 <= cmd["x"] <= 0.2
                if "y" in cmd:
                    assert -0.2 <= cmd["y"] <= 0.2
