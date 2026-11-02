"""Generated resource continuation identities survive the public MCP roundtrip."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from app.ai import ask, agentic_tools, capability_contract
from app.ai.schemas import AiAskRequest
from test_omi_mcp_server import load_server_module
from test_resource_ask_refresh import db, isolated_clock_and_network  # noqa: F401


def generated(db):
    initial=ask.ask(db,AiAskRequest(contract_version='omi.decision.v4', question='GC daily evidence',
        target={'type':'resource_asset','id':'GC'},mode='data_only',output='evidence_only',payload_level='full',
        realtime_policy='cache_only',allow_external_fetch=False,allow_llm=False,allow_write=False,
        refresh_policy={'mode':'off','before_answer':False},selection={'include':['daily.ohlcv'],'max_response_bytes':200000}))
    return initial['continuation']['fill_plan']['actions'][0]['invoke']['arguments']


def forwarded(invoke):
    with patch.dict('os.environ',{},clear=True): server=load_server_module()
    args={key:value for key,value in invoke.items() if key not in {'allow_external_fetch','allow_llm','allow_write'}}
    args.update(mode='data_only', refresh_if_missing=False, realtime_policy='cache_only',
        refresh_policy={'mode':'off','before_answer':False}, tool_budget={'max_calls':0,'max_external_fetches':0,'max_total_seconds':20})
    return server._ask_payload(args)


@pytest.mark.parametrize('market',[None,'resource','RESOURCE'])
def test_generated_resource_invoke_roundtrips_without_rewriting_binding(db,market):
    invoke=generated(db)
    if market: invoke['target']['market']=market
    body=forwarded(invoke)
    assert body['continuation']==invoke['continuation']
    result=ask.ask(db,AiAskRequest(**body))
    assert result['request_valid'] is True
    assert result['execution']['tool_runs']==[]
    assert result['continuation']['fill_plan']['plan_id']==invoke['continuation']['plan_id']


@pytest.mark.parametrize('mutation',['symbol','market','plan_actions','expanded_selected'])
def test_resource_continuation_rejects_changed_identity_before_market_io(db,mutation):
    body=forwarded(generated(db))
    if mutation=='symbol': body['target']['id']='CL'
    if mutation=='market': body['target']['market']='US'
    if mutation=='plan_actions': body['continuation']['plan_action_ids']=['fill_not_the_plan']
    if mutation=='expanded_selected': body['continuation']['selected_action_ids'].append('fill_not_the_plan')
    with patch.object(agentic_tools,'read_resource_asset_context',side_effect=AssertionError('read before binding')) as read, \
         patch.object(agentic_tools,'run_resource_asset_tool_session',side_effect=AssertionError('command before binding')) as command:
        with pytest.raises(ValueError,match='Continuation'):
            ask.ask(db,AiAskRequest(**body))
    read.assert_not_called();command.assert_not_called()


def test_resource_case_alias_keeps_action_identity_but_not_other_markets():
    target={'type':'resource_asset','id':'GC','market':'resource'}
    action=lambda value: capability_contract.fill_action_id(capability_id='daily.ohlcv',target=value)
    assert action(target)==action({**target,'market':'RESOURCE'})
    assert action(target)!=action({**target,'market':'US'})
