"""Tests for usage-derived Family Link bonus remaining tracking."""

from custom_components.familylink.coordinator import _derive_bonus_tracking


def _time_data(*, override_id="bonus-1", granted=60, used=100):
    return {
        "bonus_override_id": override_id,
        "bonus_minutes": granted,
        "used_minutes": used,
    }


def _usage(*, attributed=100.0, sessions=1, date="2026-08-13"):
    return {
        "app_attributed_minutes": attributed,
        "session_count": sessions,
        "date": date,
    }


def test_new_bonus_starts_from_granted_duration() -> None:
    """A new override captures baselines and waits for another observation."""
    tracking, fields = _derive_bonus_tracking(
        _time_data(),
        _usage(),
        None,
    )

    assert tracking is not None
    assert tracking["applied_baseline"] == 100
    assert tracking["app_baseline"] == 100
    assert fields == {
        "bonus_granted_minutes": 60.0,
        "bonus_remaining_minutes": 60.0,
        "bonus_remaining_quality": "initializing",
        "bonus_remaining_source": "baseline",
        "bonus_observation_count": 1,
    }


def test_bonus_uses_larger_valid_usage_delta() -> None:
    """The fresher counter wins when Google endpoints update at different times."""
    tracking, _ = _derive_bonus_tracking(_time_data(), _usage(), None)
    tracking, fields = _derive_bonus_tracking(
        _time_data(used=104),
        _usage(attributed=106.5),
        tracking,
    )

    assert tracking is not None
    assert fields["bonus_remaining_minutes"] == 53.5
    assert fields["bonus_remaining_source"] == "appsandusage"
    assert fields["bonus_remaining_quality"] == "estimated"
    assert fields["bonus_observation_count"] == 2


def test_bonus_falls_back_when_applied_counter_is_unchanged() -> None:
    """appsandusage still advances the estimate when position 20 is stale."""
    tracking, _ = _derive_bonus_tracking(_time_data(), _usage(), None)
    _, fields = _derive_bonus_tracking(
        _time_data(used=100),
        _usage(attributed=105),
        tracking,
    )

    assert fields["bonus_remaining_minutes"] == 55
    assert fields["bonus_remaining_source"] == "appsandusage"


def test_bonus_repairs_missing_persisted_counters() -> None:
    """Malformed persisted values fall back to the current grant and counter."""
    tracking, fields = _derive_bonus_tracking(
        _time_data(used=105),
        _usage(sessions=0),
        {
            "override_id": "bonus-1",
            "granted_minutes": 60,
            "remaining_base_minutes": None,
            "remaining_minutes": None,
            "applied_baseline": None,
            "app_baseline": None,
            "usage_date": "2026-08-13",
            "observation_count": 1,
        },
    )

    assert tracking is not None
    assert tracking["applied_baseline"] == 105
    assert fields["bonus_remaining_minutes"] == 60
    assert fields["bonus_remaining_source"] == "applied_time_limits"


def test_bonus_preserves_previous_estimate_when_no_counter_is_usable() -> None:
    """An observation without either counter cannot consume estimated time."""
    tracking, fields = _derive_bonus_tracking(
        _time_data(used=None),
        _usage(sessions=0),
        {
            "override_id": "bonus-1",
            "granted_minutes": 60,
            "remaining_base_minutes": 60,
            "remaining_minutes": 55,
            "applied_baseline": 100,
            "app_baseline": None,
            "usage_date": "2026-08-13",
            "observation_count": 2,
        },
    )

    assert tracking is not None
    assert fields["bonus_remaining_minutes"] == 55
    assert fields["bonus_remaining_source"] == "none"
    assert fields["bonus_remaining_quality"] == "unavailable"


def test_bonus_preserves_remaining_across_daily_rollover() -> None:
    """Counter resets start a new segment without restoring the full grant."""
    tracking, _ = _derive_bonus_tracking(_time_data(), _usage(), None)
    tracking, fields = _derive_bonus_tracking(
        _time_data(used=110),
        _usage(attributed=111),
        tracking,
    )
    assert fields["bonus_remaining_minutes"] == 49

    tracking, fields = _derive_bonus_tracking(
        _time_data(used=0),
        _usage(attributed=0, sessions=0, date="2026-08-14"),
        tracking,
    )
    assert tracking is not None
    assert fields["bonus_remaining_minutes"] == 49

    _, fields = _derive_bonus_tracking(
        _time_data(used=3),
        _usage(attributed=2, date="2026-08-14"),
        tracking,
    )
    assert fields["bonus_remaining_minutes"] == 46


def test_applied_counter_reset_detects_rollover_before_appsandusage() -> None:
    """A position-20 rollback starts a new segment even if usage date is stale."""
    tracking, _ = _derive_bonus_tracking(_time_data(), _usage(), None)
    tracking, fields = _derive_bonus_tracking(
        _time_data(used=110),
        _usage(attributed=111),
        tracking,
    )
    assert fields["bonus_remaining_minutes"] == 49

    tracking, fields = _derive_bonus_tracking(
        _time_data(used=2),
        _usage(attributed=111, date="2026-08-13"),
        tracking,
    )
    assert tracking is not None
    assert tracking["applied_baseline"] == 2
    assert fields["bonus_remaining_minutes"] == 49


def test_replacement_override_gets_new_baselines() -> None:
    """A replacement bonus does not inherit consumption from the old override."""
    tracking, _ = _derive_bonus_tracking(_time_data(), _usage(), None)
    tracking, fields = _derive_bonus_tracking(
        _time_data(override_id="bonus-2", granted=15, used=120),
        _usage(attributed=121),
        tracking,
    )

    assert tracking is not None
    assert tracking["override_id"] == "bonus-2"
    assert fields["bonus_remaining_minutes"] == 15
    assert fields["bonus_remaining_quality"] == "initializing"


def test_inactive_bonus_clears_tracking_fields() -> None:
    """No override produces an explicit inactive shape."""
    tracking, fields = _derive_bonus_tracking(
        _time_data(override_id=None, granted=0),
        _usage(),
        {"override_id": "old"},
    )

    assert tracking is None
    assert fields["bonus_remaining_quality"] == "inactive"
    assert fields["bonus_remaining_minutes"] == 0
