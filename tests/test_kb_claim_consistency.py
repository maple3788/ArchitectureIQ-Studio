import copy
import pytest
from architecture_iq.kb.claim_consistency import audit_messages,validate_audit,gate_claim

CONTEXT={'status':'configured','config_hash':'a'*64,'budget_values':[4096,8192,16384],'steps_values':[256,512,1024,2048]}
@pytest.fixture
def claim():
 return {'text':'Within short step budgets, the higher learning rate wins.', 'rules':[{'scope':[['steps','in',[256,512,1024,2048]],['budget','in',[4096,8192,16384]]],'predict':{'higher_better':'lr'}}]}
def reply():
 return {'consistent':True,'conditions_complete':True,'conclusion_matches':True,'conditions':[{'quote':'Within short step budgets','status':'matched','rule_indices':[0],'checks':[{'rule_index':0,'path':'/scope','expected':[['steps','in',[256,512,1024,2048]],['budget','in',[4096,8192,16384]]]}]}],'issues':[],'explanation':{'text':'','status':'hypothesis'}}
def test_bound_audit_gate_and_no_mutation(claim):
 original=copy.deepcopy(claim); a=validate_audit(claim,CONTEXT,reply()); assert a['status']=='passed'; assert gate_claim(claim,CONTEXT,a)==claim; assert original==claim
 claim['text']+=' Elsewhere too.'
 with pytest.raises(ValueError): gate_claim(claim,CONTEXT,a)
def test_context_change_invalidates_audit(claim):
 a=validate_audit(claim,CONTEXT,reply())
 with pytest.raises(ValueError): gate_claim(claim,{**CONTEXT,'config_hash':'b'*64},a)
@pytest.mark.parametrize('scope',[[],[['steps','le',2048]],{'any':[[['steps','in',[256,512,1024,2048]],['budget','in',[4096,8192,16384]]],['lr','ge',.001]]}])
def test_budget_scope_is_required_in_every_branch(claim,scope):
 claim['rules'][0]['scope']=scope; r=reply(); r['conditions'][0]['checks'][0]['expected']=scope
 assert 'budget_scope_missing' in [x['code'] for x in validate_audit(claim,CONTEXT,r)['issues']]
@pytest.mark.parametrize('bad',['true','false',1,None])
def test_no_truthy_boolean_bypass(claim,bad):
 r=reply();r['consistent']=bad; assert validate_audit(claim,CONTEXT,r)['status']!='passed'
def test_reference_and_causality(claim):
 claim['text']+=' This happens because gradients need larger steps.'
 r=reply();r['explanation']['text']='because gradients need larger steps';r['conditions'][0]['checks'][0]['path']='/missing'
 a=validate_audit(claim,CONTEXT,r); assert a['status']=='needs_review';assert a['explanation']['status']=='hypothesis';assert any(x['code']=='invalid_rule_reference' for x in a['issues'])
def test_unknown_budget_is_not_inferred(claim):
 a=validate_audit(claim,{},reply()); assert any(x['code']=='budget_provenance_missing' for x in a['issues'])
def test_failed_reviewer_blocks(claim):
 a=validate_audit(claim,CONTEXT,None);assert a['status']=='unchecked'
 with pytest.raises(ValueError): gate_claim(claim,CONTEXT,a)
def test_prompt_has_no_default_threshold_authority(claim):
 prompt=str(audit_messages(claim,CONTEXT));assert 'NOT defaults' in prompt; assert 'EVERY applicability' in prompt


@pytest.mark.parametrize('field,bad', [
 ('issues', None), ('issues', 'wrong conclusion'),
 ('issues', {'message': 'wrong conclusion'}), ('issues', ['wrong conclusion']),
 ('issues', [{}]), ('issues', [{'message': ''}]),
 ('issues', [{'message': 'wrong conclusion', 'code': []}]),
 ('explanation', None), ('explanation', ''), ('explanation', {}),
 ('explanation', {'text': '', 'status': 'proven'}),
 ('explanation', {'text': 1, 'status': 'hypothesis'}),
])
def test_malformed_review_fields_block_registration(claim, field, bad):
 review = reply()
 review[field] = bad
 audit = validate_audit(claim, CONTEXT, review)
 assert audit['status'] == 'needs_review'
 with pytest.raises(ValueError):
  gate_claim(claim, CONTEXT, audit)


@pytest.mark.parametrize('field', ['issues', 'explanation'])
def test_missing_review_fields_block_registration(claim, field):
 review = reply()
 del review[field]
 audit = validate_audit(claim, CONTEXT, review)
 assert audit['status'] == 'needs_review'
 with pytest.raises(ValueError):
  gate_claim(claim, CONTEXT, audit)


@pytest.mark.parametrize('rules', [[], None, {}, [None]])
def test_gate_rejects_empty_or_malformed_rules_even_with_bound_pass(claim, rules):
 from architecture_iq.kb.claim_consistency import CHECKER_VERSION, claim_hash, digest
 claim['rules'] = rules
 audit = {'status': 'passed', 'checker_version': CHECKER_VERSION,
          'claim_hash': claim_hash(claim), 'budget_context_hash': digest(CONTEXT)}
 with pytest.raises(ValueError, match='nonempty'):
  gate_claim(claim, CONTEXT, audit)
