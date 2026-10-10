"""Form descriptors backed by the same family pools used for validation."""
from copy import deepcopy


def family_form_schema(profile, family) -> dict:
    config = profile.family_config(family.name)
    descriptors = {
        'input_dim': {'name': 'input_dim', 'label': '输入维度', 'type': 'integer',
                      'enum': config.get('input_dims', [4]), 'min': 1, 'max': 100000, 'unit': '维'},
        'rule_family': {'name': 'rule_family', 'label': '生成规则', 'type': 'string',
                        'enum': config.get('rule_families', []), 'unit': ''},
    }
    fields = []
    for name in family.instance_option_names:
        if name not in descriptors:
            raise ValueError(f'Studio validation does not yet support family option {name!r}')
        fields.append({**descriptors[name], 'required': False, 'default_mode': 'sample'})
    return {'version': 1, 'editable_fields': deepcopy(fields),
            'read_only_facts': [{'name': key, 'label': key, 'value': deepcopy(value)} for key, value in config.items()]}


def validate_family_options(profile, family, options: dict) -> dict:
    if not isinstance(options, dict):
        raise ValueError('family_options must be an object')
    fields = {f['name']: f for f in family_form_schema(profile, family)['editable_fields']}
    if set(options) - set(fields):
        raise ValueError(f'{family.name} does not accept family_options {sorted(set(options) - set(fields))}')
    for name, value in options.items():
        field = fields[name]
        expected = int if field['type'] == 'integer' else str
        if type(value) is not expected or value not in field['enum']:
            raise ValueError(f'{name} must be one of {field["enum"]}')
        if expected is int and not field['min'] <= value <= field['max']:
            raise ValueError(f'{name} is outside the supported range')
    return deepcopy(options)
