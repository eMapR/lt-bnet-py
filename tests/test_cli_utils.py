import pytest

import cli_utils

BASE_PARAM = {k: object() for k in cli_utils.REQUIRED_PARAM_KEYS}
BASE_PARAM["ADS_path"] = {"on": False}


def _param(**overrides):
    param = dict(BASE_PARAM)
    param.update(overrides)
    return param


class TestNormalizeParametersDeclinePath:
    """decline_path is the real signal pipeline_modes.py branches on; these
    cover its derivation from the legacy option1/option3 convention plus
    explicit overrides, since getting this wrong silently flips which
    decline algorithm a real run executes."""

    def _minimal(self, **overrides):
        param = {"project_name": "test-proj", "target": 2025}
        param.update(overrides)
        return param

    def test_option3_derives_ltsd(self):
        param = cli_utils.normalize_parameters(self._minimal(configName="option3"))
        assert param["decline_path"] == "ltsd"

    def test_option1_derives_snic(self):
        param = cli_utils.normalize_parameters(self._minimal(configName="option1"))
        assert param["decline_path"] == "snic"

    def test_no_configName_defaults_to_ltsd(self):
        # configName defaults to f"option{logic_version}" and logic_version
        # defaults to "3", so an unconfigured file still gets the LTSD path -
        # matches every real template's implicit default.
        param = cli_utils.normalize_parameters(self._minimal())
        assert param["configName"] == "option3"
        assert param["decline_path"] == "ltsd"

    def test_explicit_decline_path_overrides_configName_derivation(self):
        # A self-describing configName ("ltsd") doesn't contain "3", so a
        # config using the new convention MUST set decline_path itself -
        # confirms the explicit value wins over the substring fallback.
        param = cli_utils.normalize_parameters(
            self._minimal(configName="ltsd", decline_path="ltsd")
        )
        assert param["decline_path"] == "ltsd"

    def test_explicit_decline_path_snic_with_new_style_configName(self):
        param = cli_utils.normalize_parameters(
            self._minimal(configName="snic", decline_path="snic")
        )
        assert param["decline_path"] == "snic"


class TestValidateParameters:
    def test_complete_ltsd_param_passes(self):
        cli_utils.validate_parameters(_param(configName="option3", decline_path="ltsd"))

    def test_missing_base_key_raises(self):
        param = _param(configName="option3", decline_path="ltsd")
        del param["aoi"]
        with pytest.raises(ValueError, match="aoi"):
            cli_utils.validate_parameters(param)

    def test_snic_path_without_snic_keys_raises(self):
        with pytest.raises(ValueError, match="LTSDname.*snicName|snicName.*LTSDname"):
            cli_utils.validate_parameters(_param(configName="option1", decline_path="snic"))

    def test_snic_path_with_snic_keys_passes(self):
        cli_utils.validate_parameters(
            _param(configName="option1", decline_path="snic", LTSDname=object(), snicName=object())
        )

    def test_ltsd_path_does_not_require_snic_keys(self):
        cli_utils.validate_parameters(_param(configName="option3", decline_path="ltsd"))

    def test_new_style_configName_on_snic_path_still_requires_snic_keys(self):
        # Confirms validation tracks decline_path, not a "3" in configName
        # substring check - a self-describing configName ("snic") must
        # still be caught if LTSDname/snicName are missing.
        with pytest.raises(ValueError, match="LTSDname.*snicName|snicName.*LTSDname"):
            cli_utils.validate_parameters(_param(configName="snic", decline_path="snic"))

    def test_missing_configName_raises(self):
        param = _param(decline_path="ltsd")
        del param["configName"]
        with pytest.raises(ValueError, match="configName"):
            cli_utils.validate_parameters(param)

    def test_ads_path_off_does_not_require_ads(self):
        cli_utils.validate_parameters(
            _param(configName="option3", decline_path="ltsd", ADS_path={"on": False})
        )

    def test_ads_path_on_without_ads_raises(self):
        with pytest.raises(ValueError, match="ads"):
            cli_utils.validate_parameters(
                _param(configName="option3", decline_path="ltsd", ADS_path={"on": True})
            )

    def test_ads_path_on_with_ads_passes(self):
        cli_utils.validate_parameters(
            _param(
                configName="option3",
                decline_path="ltsd",
                ADS_path={"on": True},
                ads=object(),
            )
        )
