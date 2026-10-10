import pytest

from architecture_iq.studio.generation import capabilities, validate_generation, _load
from architecture_iq.registry import get_dataset_family
from test_studio_generation import config


def test_schema_fields_match_real_family_options_and_profile_enums():
    for profile in capabilities()['profiles']:
        for family in profile['families']:
            schema = family['form_schema']
            assert {field['name'] for field in schema['editable_fields']} == set(family['options'])
            for field in schema['editable_fields']:
                assert field['default_mode'] == 'sample' and field['required'] is False
                assert field['enum'] == family['config'].get('input_dims', [4]) if field['name'] == 'input_dim' else field['enum'] == family['config']['rule_families']
            assert schema['read_only_facts']


def test_univariate_exposes_read_only_rules_and_rejects_fake_noise_option():
    profile = next(p for p in capabilities()['profiles'] if p['name'] == 'v1.4')
    family = next(f for f in profile['families'] if f['name'] == 'univariate_regression')
    assert family['form_schema']['editable_fields'] == []
    with pytest.raises(ValueError): validate_generation(config(family_options={'noise_std': .1}))


def test_form_validation_accepts_only_exact_typed_enum_members():
    from architecture_iq.studio.generation_forms import validate_family_options
    profile = _load('v1.4')
    family = get_dataset_family('multivariate_regression')
    for bad in (True, 1.5, '4', 999999):
        with pytest.raises(ValueError): validate_family_options(profile, family, {'input_dim': bad})
    for value in profile.family_config(family.name)['input_dims']:
        assert validate_family_options(profile, family, {'input_dim': value}) == {'input_dim': value}
