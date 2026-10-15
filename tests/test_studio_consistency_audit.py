import json
from architecture_iq.kb.claim_consistency import claim_hash,CHECKER_VERSION
from architecture_iq.studio.loop_observer import LoopObserver
from test_studio_loop_observer import capture,configuration


def test_audit_annotations_are_content_bound_and_do_not_change_sealed_capture(tmp_path):
 value=capture(); claim=value['claims'][0];value['claim_details']['C1']['claim']=dict(claim)
 observer=LoopObserver(tmp_path,config=configuration(),reader=lambda _:value)
 assert observer.poll_once()
 before=observer.capture(); token=before['observation']['content_hash']
 audit={'status':'needs_review','issues':[{'code':'budget_scope_missing','message':'预算缺少约束'}]}
 report={'checker_version':CHECKER_VERSION,'source_identity':observer.config.identity,'claims':{'C1':{'version':2,'claim_hash':claim_hash(claim),'audit':audit}}}
 (observer.directory/'consistency_audit.json').write_text(json.dumps(report))
 assert observer.snapshot()['claims'][0]['consistency_audit']==audit
 assert observer.claim('C1')['claim']['consistency_audit']==audit
 assert observer.capture()['observation']['content_hash']==token
 assert 'consistency_audit' not in observer.capture()['claims'][0]
 changed={**claim,'text':'Changed wording'}
 assert observer.audit_claims([changed])=={}
 assert observer.audit_claims([{**claim,'version':3}])=={}
 report['source_identity']='b'*64
 (observer.directory/'consistency_audit.json').write_text(json.dumps(report))
 assert observer.audit_claims([claim])=={}

def test_missing_or_bad_audit_does_not_break_observation(tmp_path):
 observer=LoopObserver(tmp_path,config=configuration(),reader=lambda _:capture())
 observer.poll_once()
 assert observer.audit_claims(capture()['claims'])=={}
 (observer.directory/'consistency_audit.json').write_text('partial')
 assert observer.snapshot()['execution']['status']=='unknown'

def test_new_runtime_audit_survives_public_projection_and_capture(tmp_path):
 from architecture_iq.studio.loop_source import _claim
 raw={**capture()['claims'][0], 'explanation':{'text':'A possible mechanism.', 'status':'hypothesis'}}
 audit={'checker_version':CHECKER_VERSION,'claim_hash':claim_hash(raw),'status':'passed','issues':[], 'consistent':True}
 raw['consistency']=audit
 public=_claim(raw)
 assert public['explanation']==raw['explanation']
 assert public['consistency_audit']['claim_hash']==claim_hash(raw)
 assert _claim(public)['consistency_audit']==public['consistency_audit']
 value=capture();value['claims']=[public];value['claim_details']['C1']['claim']=public
 observer=LoopObserver(tmp_path,config=configuration(),reader=lambda _:value)
 assert observer.poll_once()
 assert observer.snapshot()['claims'][0]['consistency_audit']['status']=='passed'
 assert observer.audit_claims([public])['C1']['status']=='passed'
 public['text']='Changed'
 assert 'consistency_audit' not in _claim(public)
 assert observer.audit_claims([public])=={}
