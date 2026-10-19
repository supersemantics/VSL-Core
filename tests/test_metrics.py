import math

import pytest

from vsl_core.metrics import (
    EEF,
    GAMMA_MONITORING_THRESHOLD,
    GES,
    JACOBIAN_RED_FLAG_THRESHOLD,
    KL_MONITORING_THRESHOLD,
    ROBUST_GAMMA_DEFAULT_THRESHOLD,
    ROBUST_GAMMA_HIGH_STAKES_THRESHOLD,
    AssuranceBasis,
    AssuranceLevel,
    Beta,
    Delta,
    EEFZone,
    F2Modification,
    GammaEstimate,
    Threshold,
)


def test_robust_gamma_formula():
    # Gamma* = Gamma_hat * (1 / (1 + delta))
    estimate = GammaEstimate(gamma_hat=1.2, delta_estimation_error=0.1)
    assert math.isclose(estimate.robust_gamma(), 1.2 * (1 / 1.1))


def test_delta_within_the_threshold_allowance_does_not_raise_the_bar():
    # 1.1 already includes a 10% allowance; delta=0.1 must not count it twice.
    # (Before rules version 2026.10 this was denied: 1.15 / 1.1 = 1.045 < 1.1.)
    estimate = GammaEstimate(gamma_hat=1.15, delta_estimation_error=0.1)
    assert estimate.required_gamma_hat(ROBUST_GAMMA_DEFAULT_THRESHOLD) == ROBUST_GAMMA_DEFAULT_THRESHOLD
    assert estimate.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD)


def test_delta_above_the_threshold_allowance_raises_the_bar():
    # delta=0.2 against 1.1: the bar becomes 1 + 0.2 = 1.2.
    assert math.isclose(GammaEstimate(gamma_hat=1.0, delta_estimation_error=0.2).required_gamma_hat(1.1), 1.2)
    assert not GammaEstimate(gamma_hat=1.15, delta_estimation_error=0.2).sufficient(1.1)
    assert GammaEstimate(gamma_hat=1.25, delta_estimation_error=0.2).sufficient(1.1)


@pytest.mark.parametrize(
    "gamma_hat, threshold, expected",
    [
        (1.30, ROBUST_GAMMA_DEFAULT_THRESHOLD, True),  # well inside policy
        (1.05, ROBUST_GAMMA_DEFAULT_THRESHOLD, False),  # above 1, within the margin
        (0.95, ROBUST_GAMMA_DEFAULT_THRESHOLD, False),  # drift winning
        (1.10, ROBUST_GAMMA_DEFAULT_THRESHOLD, False),  # exactly on the bar: strict >
        (1.15, ROBUST_GAMMA_HIGH_STAKES_THRESHOLD, False),  # high stakes
        (1.25, ROBUST_GAMMA_HIGH_STAKES_THRESHOLD, True),
    ],
)
def test_zero_delta_behaviour_is_unchanged(gamma_hat, threshold, expected):
    assert GammaEstimate(gamma_hat=gamma_hat).sufficient(threshold) is expected


@pytest.mark.parametrize("delta", [0.0, 0.05, 0.1, 0.15, 0.2, 0.5])
@pytest.mark.parametrize("gamma_hat", [0.9, 1.0, 1.05, 1.1, 1.11, 1.2, 1.21, 1.6])
def test_a_pass_always_means_robust_gamma_above_one(gamma_hat, delta):
    estimate = GammaEstimate(gamma_hat=gamma_hat, delta_estimation_error=delta)
    if estimate.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD):
        assert estimate.robust_gamma() > 1.0


def test_sufficient_default_threshold_is_robust_default():
    estimate = GammaEstimate(gamma_hat=1.3, delta_estimation_error=0.1)
    assert estimate.sufficient() == estimate.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD)


def test_zero_estimation_error_means_robust_equals_raw():
    estimate = GammaEstimate(gamma_hat=1.1)
    assert estimate.robust_gamma() == 1.1


def test_high_stakes_threshold_is_stricter():
    assert ROBUST_GAMMA_HIGH_STAKES_THRESHOLD > ROBUST_GAMMA_DEFAULT_THRESHOLD


def test_delta_from_gamma():
    delta = Delta.from_gamma(gamma=1.5, energy_gap=2.0)
    assert delta.value == 3.0


def test_ges_compute_and_trigger():
    ges = GES.compute(governed_kl_integral=0.5, ungoverned_kl_integral=1.0)
    assert ges.score == 0.5
    assert not ges.triggers_specification_update(theta=0.3)
    assert ges.triggers_specification_update(theta=0.6)


def test_ges_governance_made_things_worse():
    ges = GES.compute(governed_kl_integral=1.5, ungoverned_kl_integral=1.0)
    assert ges.score < 0


def test_ges_rejects_zero_baseline():
    with pytest.raises(ValueError):
        GES.compute(governed_kl_integral=0.5, ungoverned_kl_integral=0.0)


def test_eef_zones():
    insufficient_gamma = GammaEstimate(gamma_hat=0.5)
    sufficient_gamma = GammaEstimate(gamma_hat=2.0)

    optimal_eef = EEF.compute(cost_of_pre_node=1.0, max_sustainable_cost=2.0)
    over_eef = EEF.compute(cost_of_pre_node=3.0, max_sustainable_cost=2.0)

    assert optimal_eef.zone(insufficient_gamma) == EEFZone.INSUFFICIENT
    assert optimal_eef.zone(sufficient_gamma) == EEFZone.OPTIMAL
    assert over_eef.zone(sufficient_gamma) == EEFZone.OVER_GOVERNANCE


def test_eef_rejects_zero_max_cost():
    with pytest.raises(ValueError):
        EEF.compute(cost_of_pre_node=1.0, max_sustainable_cost=0.0)


def test_assurance_level_string_values():
    assert AssuranceLevel.HIGH.value == "HIGH"
    assert AssuranceLevel.MEDIUM.value == "MEDIUM"
    assert AssuranceLevel.LOW.value == "LOW"


@pytest.mark.parametrize(
    "f1, f2, expected",
    [
        (False, F2Modification.FULL, AssuranceLevel.LOW),
        (False, F2Modification.PARTIAL, AssuranceLevel.LOW),
        (False, F2Modification.INDIRECT, AssuranceLevel.LOW),
        (False, F2Modification.NONE, AssuranceLevel.LOW),
        (True, F2Modification.FULL, AssuranceLevel.HIGH),
        (True, F2Modification.PARTIAL, AssuranceLevel.MEDIUM),
        (True, F2Modification.INDIRECT, AssuranceLevel.MEDIUM),
        (True, F2Modification.NONE, AssuranceLevel.LOW),
    ],
)
def test_assurance_basis_derived_level_full_table(f1, f2, expected):
    basis = AssuranceBasis(f1_pre_commitment=f1, f2_modification=f2)
    assert basis.derived_level == expected


def test_assurance_basis_logit_adjustment_is_high():
    # Concrete spec example: logit adjustment before sampling -- F1 yes, F2 yes -> HIGH.
    basis = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)
    assert basis.derived_level == AssuranceLevel.HIGH


def test_assurance_basis_system_prompt_is_medium():
    # Concrete spec example: system prompt -- F1 yes, F2 partial -> MEDIUM.
    basis = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.PARTIAL)
    assert basis.derived_level == AssuranceLevel.MEDIUM


def test_assurance_basis_output_filtering_is_low():
    # Concrete spec example: output filtering (post-generation) -- F1 no -> LOW.
    basis = AssuranceBasis(f1_pre_commitment=False, f2_modification=F2Modification.NONE)
    assert basis.derived_level == AssuranceLevel.LOW


def test_assurance_basis_rejects_none_f2_modification():
    # f2_modification=None must not silently fall through derived_level to
    # an unflagged LOW -- that was a real, previously-shipped bug.
    with pytest.raises(TypeError):
        AssuranceBasis(f1_pre_commitment=True, f2_modification=None)


def test_assurance_basis_rejects_non_enum_f2_modification():
    with pytest.raises(TypeError):
        AssuranceBasis(f1_pre_commitment=True, f2_modification="FULL")


def test_assurance_basis_rejects_none_f1_pre_commitment():
    # f1_pre_commitment=None is falsy, so `not self.f1_pre_commitment` would
    # silently derive LOW without this check -- the same unflagged-LOW bug
    # shape as f2_modification=None, just on the other field.
    with pytest.raises(TypeError):
        AssuranceBasis(f1_pre_commitment=None, f2_modification=F2Modification.FULL)


def test_assurance_basis_rejects_non_bool_f1_pre_commitment():
    # bool is a subclass of int in Python, so this also confirms the check
    # uses isinstance(x, bool) specifically rather than isinstance(x, int),
    # which would wrongly accept 1/0 as valid.
    with pytest.raises(TypeError):
        AssuranceBasis(f1_pre_commitment=1, f2_modification=F2Modification.FULL)


def test_beta_is_a_bare_value_holder():
    beta = Beta(value=2.5)
    assert beta.value == 2.5


def test_threshold_construction():
    threshold = Threshold(name="custom", value=0.42, unit="nats")
    assert threshold.name == "custom"
    assert threshold.value == 0.42
    assert threshold.unit == "nats"


def test_threshold_default_unit_is_empty_string():
    threshold = Threshold(name="dimensionless", value=1.1)
    assert threshold.unit == ""


def test_gamma_monitoring_threshold_derives_from_existing_constant():
    assert GAMMA_MONITORING_THRESHOLD.value == ROBUST_GAMMA_DEFAULT_THRESHOLD


def test_jacobian_red_flag_threshold_value():
    assert JACOBIAN_RED_FLAG_THRESHOLD.value == 0.05


def test_kl_monitoring_threshold_value_and_unit():
    assert KL_MONITORING_THRESHOLD.value == 0.15
    assert KL_MONITORING_THRESHOLD.unit == "nats"
