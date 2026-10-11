"""Typed material routes for the controller-owned, bounded rule refinement protocol."""
from __future__ import annotations

from copy import deepcopy
from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.methods import resolve_method
from .contracts import DEFAULT_LIMITS, METHOD_ID, PROTOCOL, fields, identifier, text, validate_limits
from .challenges import prepare_challenge
from architecture_iq.studio.generation import validate_generation

CORE={'input':'question_input','initialize':'rule_initializer','verify':'rule_verify','revise':'rule_reviser',
      'accept':'rule_accept','challenge':'rule_challenge','save':'rule_save'}
LABELS={'input':'研究题池','initialize':'初始规则','verify':'程序验证','revise':'修订规则',
        'accept':'不退步验收','challenge':'新题挑战','save':'保存最好 KB'}
# All routes carry whole typed material. Loop transitions are owned by the runner.
FIXED_ROUTES=[('input','initialize','public_cases','always'),('input','verify','public_cases','always'),
              ('initialize','verify','rule_kb','always'),('verify','accept','sealed_feedback','always'),
              ('revise','accept','patch','always'),('accept','challenge','rule_kb','pool_passed'),
              ('accept','save','decision','stopped'),('challenge','save','decision','target_reached')]


def material_edge(source,target,port,condition='always'):
    return dict(id=f'{source}-{target}-{port}',source=source,target=target,source_handle=port,target_handle=port,
                mapping={port:port},condition=condition)


def default_rule_workflow():
    nodes=[]
    for i,(key,kind) in enumerate(CORE.items()):
        config={}
        if key=='input': config={'dataset_binding':None,'data_mode':'single'}
        if key=='initialize': config={'mode':'import','source':None,'model_id':'','prompt':''}
        if key=='revise': config={'model_id':'','prompt':''}
        nodes.append(dict(id=key,type=kind,label=LABELS[key],position={'x':i%4*270,'y':i//4*240},config=config))
    return dict(schema_version=2,name='规则 KB 闭环',nodes=nodes,
                edges=[material_edge(*route) for route in FIXED_ROUTES]+[material_edge('verify','revise','sealed_feedback','needs_revision')],
                settings={'method_id':METHOD_ID,'method_version':'1','limits':deepcopy(DEFAULT_LIMITS),'generation':{}})


def _compile(spec):
    fields(spec,{'schema_version','name','nodes','edges','settings'},{'schema_version','name','nodes','edges','settings'})
    if type(spec['schema_version']) is not int or spec['schema_version']!=2:
        raise ValueError('Rule workflows require schema_version 2')
    text(spec['name'],maximum=300)
    settings=spec['settings']
    fields(settings,{'method_id','method_version','limits','generation'},{'method_id','method_version','limits','generation'})
    method=resolve_method(settings)
    if method['id']!=METHOD_ID:
        raise ValueError('Schema v2 belongs only to rule_refinement')
    limits=validate_limits(settings['limits'])
    generation=validate_generation(settings['generation'])
    prepare_challenge(generation,attempt_index=limits['max_generation_attempts'],questions_per_batch=limits['questions_per_batch'])
    if not isinstance(spec['nodes'],list) or not 7<=len(spec['nodes'])<=10:
        raise ValueError('Seven protected nodes and at most three grouping nodes required')
    nodes={}
    groups=set()
    for node in spec['nodes']:
        fields(node,{'id','type','label','position','config'},{'id','type','label','position','config'})
        key=identifier(node['id'])
        if key in nodes:
            raise ValueError('Duplicate node')
        nodes[key]=node
        text(node['label'],required=False,maximum=300)
        fields(node['position'],{'x','y'},{'x','y'})
        if any(type(v) not in (int,float) for v in node['position'].values()):
            raise ValueError('Invalid node position')
        config=node['config']
        if key in CORE:
            if node['type']!=CORE[key]:
                raise ValueError('Protected node role cannot change')
            if key=='input':
                fields(config,{'dataset_binding','data_mode'},{'dataset_binding','data_mode'})
                if config['data_mode'] not in {'single','pairs'} or config['dataset_binding'] is not None and not isinstance(config['dataset_binding'],dict):
                    raise ValueError('Invalid dataset selection')
                if (config['data_mode']=='pairs') != (generation['mode']=='paired'):
                    raise ValueError('Dataset mode and generation mode must match')
            elif key in {'initialize','revise'}:
                allowed={'model_id','prompt'}|({'mode','source'} if key=='initialize' else set())
                fields(config,allowed,allowed)
                text(config['model_id'],required=False,maximum=200)
                text(config['prompt'],required=False)
                if key=='initialize' and (config['mode'] not in {'import','model'} or config['source'] is not None and not isinstance(config['source'],dict)):
                    raise ValueError('Invalid initialization configuration')
            else:
                fields(config,set())
        elif node['type']=='group_cases':
            fields(config,{'strategy'},{'strategy'})
            if config['strategy'] not in {'type','rule','family'}:
                raise ValueError('Unsupported case grouping')
            groups.add(key)
        else:
            raise ValueError('Unsupported executable node')
    if set(CORE)-set(nodes):
        raise ValueError('Required protected node is missing')
    if not isinstance(spec['edges'],list):
        raise ValueError('Material edges must be a list')
    routes=set();edge_ids=set()
    for edge in spec['edges']:
        fields(edge,{'id','source','target','source_handle','target_handle','mapping','condition'},
               {'id','source','target','source_handle','target_handle','mapping','condition'})
        key=identifier(edge['id'])
        if key in edge_ids: raise ValueError('Duplicate edge identifier')
        edge_ids.add(key)
        port=edge['source_handle']
        if (not isinstance(port,str) or port not in {'public_cases','rule_kb','sealed_feedback','patch','decision'}
                or edge['target_handle']!=port or edge['mapping']!={port:port}):
            raise ValueError('Connections must reference whole matching typed material')
        if not all(isinstance(edge[k],str) for k in ('source','target','condition')):
            raise ValueError('Invalid connection')
        route=(edge['source'],edge['target'],port,edge['condition'])
        if route in routes: raise ValueError('Duplicate material route')
        routes.add(route)
    remaining=routes-set(FIXED_ROUTES)
    if not set(FIXED_ROUTES)<=routes:
        raise ValueError('Protected validation, acceptance or output route is missing')
    grouping=[];visited=[];source='verify'
    while True:
        condition='needs_revision' if source=='verify' else 'always'
        next_routes=[r for r in remaining if r[0]==source and r[2:] == ('sealed_feedback',condition)]
        if len(next_routes)!=1: raise ValueError('Feedback requires one ordered grouping route to revise')
        route=next_routes[0];remaining.remove(route);target=route[1]
        if target=='revise': break
        if target not in groups or target in visited:
            raise ValueError('Unknown node or extra material cycle')
        visited.append(target);grouping.append(nodes[target]['config']['strategy']);source=target
    if remaining or set(visited)!=groups or len(set(grouping))!=len(grouping):
        raise ValueError('Unreachable node, duplicate grouping or unsupported material route')
    semantic=dict(protocol=PROTOCOL,method=method,limits=limits,generation=generation,grouping=grouping,
                  nodes={k:nodes[k]['config'] for k in CORE})
    return dict(workflow=deepcopy(spec),method=method,protocol=PROTOCOL,workflow_hash=canonical_hash(spec),
                execution_hash=canonical_hash(semantic),limits=limits,
                initialization=deepcopy(nodes['initialize']['config']),dataset_input=deepcopy(nodes['input']['config']),
                grouping=grouping,model_nodes={k:deepcopy(nodes[k]['config']) for k in ('initialize','revise')},
                generation=generation,execution_order=['input','initialize','verify',*visited,'revise','accept','challenge','save'])


def validate_rule_workflow(spec):
    try:
        _compile(spec)
        return {'valid':True,'errors':[]}
    except (ValueError,TypeError,KeyError) as exc:
        return {'valid':False,'errors':[str(exc)]}


def compile_rule_workflow(spec):
    try:
        return _compile(spec)
    except (ValueError,TypeError,KeyError) as exc:
        raise ValueError(f'Invalid rule workflow: {exc}') from None
