import pytest

import cli_utils

BASE_PARAM = {k: object() for k in cli_utils.REQUIRED_PARAM_KEYS}


def _param(**overrides):
    param = dict(BASE_PARAM)
    param.update(overrides)
    return param


class TestValidateParameters:
    def test_complete_option3_param_passes(self):
        cli_utils.validate_parameters(_param(configName="option3"))

    def test_missing_base_key_raises(self):
        param = _param(configName="option3")
        del param["aoi"]
        with pytest.raises(ValueError, match="aoi"):
            cli_utils.validate_parameters(param)

    def test_non_option3_without_snic_keys_raises(self):
        with pytest.raises(ValueError, match="LTSDname.*snicName|snicName.*LTSDname"):
            cli_utils.validate_parameters(_param(configName="option1"))

    def test_non_option3_with_snic_keys_passes(self):
        cli_utils.validate_parameters(
            _param(configName="option1", LTSDname=object(), snicName=object())
        )

    def test_option3_does_not_require_snic_keys(self):
        cli_utils.validate_parameters(_param(configName="option3"))

    def test_missing_configName_treated_as_non_option3(self):
        param = _param()
        del param["configName"]
        with pytest.raises(ValueError, match="configName"):
            cli_utils.validate_parameters(param)
