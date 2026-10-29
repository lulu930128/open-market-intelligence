"""Continuation spends the existing scan budget without another transport."""
from concurrent.futures import Future
from threading import Event

import pytest
from app.market.providers import twse_mis_current_breadth as provider
from app.market.providers import twse_mis_breadth_evidence as io
from test_tw_breadth_acquisition_evidence import clock, offline, message, CODES


@pytest.mark.parametrize('venue', ['TWSE','TPEX'])
def test_seventh_batch_caller_deadline_resumes_same_response_with_total_budget(clock,monkeypatch,venue):
    calls=[];resumes=[]
    class Deferred(io.AcquisitionDeadlineExceeded):
        def resume(self,seconds):
            resumes.append(seconds)
            clock.seconds += .5
            return [message(c) for c in calls[-1]]
    def bounded(fetch,seconds,codes,**kwargs):
        calls.append(codes)
        if len(calls)==7:
            clock.seconds+=4
            raise Deferred('TWSE_MIS_ACQUISITION_DEADLINE')
        clock.seconds+=1.7 if len(calls)<7 else .4
        return [message(c) for c in codes]
    monkeypatch.setattr(provider,'bounded_fetch',bounded)
    diagnostic={}
    rows,failed,count=provider._fetch_messages(CODES[:900],venue,20,diagnostics=diagnostic)
    assert len(rows)==900 and len({r['c'] for r in rows})==900
    assert failed==0 and count==len(calls)==9
    assert resumes==[pytest.approx(5.8)]
    assert clock.seconds < 20
    assert diagnostic['batches'][6]['caller_wait_seconds']==pytest.approx(4.5)
    assert diagnostic['batches'][6]['resumed_wait_seconds']==pytest.approx(.5)
    assert diagnostic['batches'][6]['initial_wait_deadline_exceeded'] is True
    assert diagnostic['batches'][6]['fetch_completed_in_budget'] is True


def test_late_future_resume_keeps_per_venue_slot_and_returns_once():
    release=Event();calls=[]
    def fetch(**kwargs):
        calls.append(kwargs['exchange'])
        release.wait(2)
        return ['completed']
    try:
        with pytest.raises(io.AcquisitionDeadlineExceeded) as caught:
            io.bounded_fetch(fetch,.01,exchange='tse')
        with pytest.raises(io.AcquisitionInFlight):
            io.bounded_fetch(fetch,.01,exchange='tse')
        assert io.bounded_fetch(lambda **kw:['other'],.2,exchange='otc')==['other']
        release.set()
        assert caught.value.resume(.5)==['completed']
        assert calls==['tse']
    finally:
        release.set()
        for future in io._IN_FLIGHT.values():
            future.result(timeout=2)
        io.reset_io_slots()


def test_resume_deadline_does_not_free_slot_or_relabel_worker_timeout():
    release=Event()
    def fetch(**kwargs):
        release.wait(2)
        raise TimeoutError('provider timeout')
    try:
        with pytest.raises(io.AcquisitionDeadlineExceeded) as caught:
            io.bounded_fetch(fetch,.01,exchange='tse')
        with pytest.raises(io.AcquisitionDeadlineExceeded):
            caught.value.resume(.01)
        with pytest.raises(io.AcquisitionInFlight):
            io.bounded_fetch(fetch,.01,exchange='tse')
        release.set()
        with pytest.raises(TimeoutError,match='provider timeout') as final:
            caught.value.resume(.5)
        assert type(final.value) is TimeoutError
    finally:
        release.set()
        for future in io._IN_FLIGHT.values():
            try:
                future.result(timeout=2)
            except TimeoutError:
                pass
        io.reset_io_slots()
