import importlib
import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.engine import analyze, loss, MODEL

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB_PATH',str(tmp_path/'test.db'))
    monkeypatch.setattr(main,'SIMULATE',False)
    with TestClient(main.app) as c:
        yield c

def test_seed_and_health(client):
    assert client.get('/api/health').json()['status']=='ok'
    s=client.get('/api/state').json()
    assert len(s['machines'])==5
    assert len(s['alerts'])==2
    assert s['analytics']['healthy']==3
    assert s['analytics']['critical']==1
    assert MODEL is not None
    assert len(client.get('/api/machines/M-02/readings').json())==36

def test_fault_explanation_resolution_and_history_bound(client):
    response=client.post('/api/simulation/scenario',json={'machine_id':'M-01','scenario':'critical'})
    assert response.status_code==200
    a=response.json()
    assert a['risk']=='High'
    assert any('Temperature' in r for r in a['reasons'])
    assert any('Vibration' in r for r in a['reasons'])
    assert 'probability' in a['disclaimer']
    active=[a for a in client.get('/api/alerts').json() if a['machine_id']=='M-01' and not a['resolved_at']]
    assert len(active)==1
    client.post(f"/api/alerts/{active[0]['id']}/acknowledge")
    assert next(a for a in client.get('/api/alerts').json() if a['id']==active[0]['id'])['acknowledged']==1
    assert client.post('/api/simulation/scenario',json={'machine_id':'M-01','scenario':'normal'}).json()['risk']=='Low'
    assert next(a for a in client.get('/api/alerts').json() if a['id']==active[0]['id'])['resolved_at']
    for _ in range(125):
        assert client.post('/api/machines/M-01/readings',json={'temperature':64,'vibration':2.2,'power':18}).status_code==200
    assert len(client.get('/api/machines/M-01/readings').json())==120

def test_crud_and_persistence(client):
    m={'name':'Test machine','zone':'Test zone','type':'CNC','baseline_power':10,'units_per_hour':100,'profit_per_unit':20}
    r=client.post('/api/machines',json=m)
    assert r.status_code==201
    id=r.json()['id']
    m['name']='Edited machine'
    assert client.put('/api/machines/'+id,json=m).json()['name']=='Edited machine'
    t={'machine_id':id,'title':'Inspect test bearings','priority':'High','due_date':'2026-11-06','status':'Scheduled'}
    r=client.post('/api/tasks',json=t)
    assert r.status_code==201
    tid=r.json()['id']
    t['status']='Completed'
    assert client.put('/api/tasks/'+tid,json=t).json()['completed_at']
    # Fresh database connections and repeated initialization preserve user data.
    main.initialize()
    with sqlite3.connect(main.DB_PATH) as con:
        assert con.execute('select name from machines where id=?',(id,)).fetchone()[0]=='Edited machine'
        assert con.execute('select status from tasks where id=?',(tid,)).fetchone()[0]=='Completed'
    assert len(client.get('/api/machines').json())==6
    assert client.delete('/api/machines/'+id).status_code==200
    assert client.get('/api/machines/'+id+'/readings').status_code==404
    assert not any(t['id']==tid for t in client.get('/api/tasks').json())

def test_loss_assistant_reports_validation_and_auth(client,monkeypatch):
    assumptions={'downtime_hours':4,'units_per_hour':180,'profit_per_unit':95,'repair_cost':12000}
    result=client.post('/api/loss',json=assumptions).json()
    assert result['production_loss']==68400
    assert result['total_impact']==80400
    assert client.get('/api/state').json()['loss']['total_impact']==80400
    assert '80,400' in client.post('/api/assistant',json={'question':'What is the estimated production loss?'}).json()['answer']
    assert 'M-02' in client.post('/api/assistant',json={'question':'Why is Machine 02 abnormal?'}).json()['answer']
    for kind in ['machines','alerts','maintenance','loss']:
        report=client.get('/api/reports/'+kind)
        assert report.status_code==200
        assert 'text/csv' in report.headers['content-type']
        assert len(report.text.splitlines())>=2
    assert client.post('/api/loss',json={**assumptions,'downtime_hours':-1}).status_code==422
    assert client.post('/api/tasks',json={'machine_id':'M-01','title':'Test','priority':'High','due_date':'bad'}).status_code==422
    assert client.get('/api/machines/missing/analysis').status_code==404
    monkeypatch.setenv('FACTORYGUARD_API_KEY','demo-test-key')
    assert client.get('/api/state').status_code==401
    assert client.get('/api/state',headers={'X-API-Key':'demo-test-key'}).status_code==200

def test_threshold_boundaries_and_fallback():
    m={'baseline_power':10}
    assert analyze(m,{'temperature':80,'vibration':2,'power':10},False)['risk']=='Medium'
    assert analyze(m,{'temperature':64,'vibration':7.1,'power':10},False)['risk']=='High'
    assert analyze(m,{'temperature':64,'vibration':2,'power':15},False)['risk']=='High'
    assert analyze(m,{'temperature':64,'vibration':2.2,'power':10},False)['risk']=='Low'
    assert loss(0,100,100,0)['total_impact']==0
