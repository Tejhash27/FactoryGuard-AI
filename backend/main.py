import asyncio
import contextlib
import csv
import io
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from .engine import CONFIG, MODEL, SEEDS, analyze, answer, loss, reading

DB_PATH = os.environ.get('FACTORYGUARD_DB','./data/factoryguard.db')
HISTORY = max(12,min(1000,int(os.environ.get('FACTORYGUARD_HISTORY_LIMIT','120'))))
SIMULATE = os.environ.get('FACTORYGUARD_SIMULATION','true').lower() == 'true'
LOCK = threading.RLock()

def now():
    return datetime.now(timezone.utc).isoformat()

@contextlib.contextmanager
def db():
    with LOCK:
        con = sqlite3.connect(DB_PATH,timeout=20)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

def write_reading(con,m,r,timestamp):
    con.execute('INSERT INTO readings(machine_id,temperature,vibration,power,timestamp) VALUES(?,?,?,?,?)',(m['id'],r['temperature'],r['vibration'],r['power'],timestamp))
    con.execute('DELETE FROM readings WHERE machine_id=? AND id NOT IN(SELECT id FROM readings WHERE machine_id=? ORDER BY id DESC LIMIT ?)',(m['id'],m['id'],HISTORY))
    a = analyze(m,r)
    active = con.execute('SELECT * FROM alerts WHERE machine_id=? AND resolved_at IS NULL',(m['id'],)).fetchone()
    if a['risk']=='Low':
        con.execute('UPDATE alerts SET resolved_at=? WHERE machine_id=? AND resolved_at IS NULL',(timestamp,m['id']))
    elif active:
        con.execute('UPDATE alerts SET risk=?,message=? WHERE id=?',(a['risk'],' '.join(a['reasons']),active['id']))
    else:
        con.execute('INSERT INTO alerts(machine_id,risk,message,created_at) VALUES(?,?,?,?)',(m['id'],a['risk'],' '.join(a['reasons']),timestamp))
    con.execute('DELETE FROM alerts WHERE id IN(SELECT id FROM alerts WHERE resolved_at IS NOT NULL ORDER BY id DESC LIMIT -1 OFFSET 300)')

def initialize():
    Path(DB_PATH).parent.mkdir(parents=True,exist_ok=True)
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY,name TEXT,zone TEXT,type TEXT,baseline_power REAL,units_per_hour REAL,profit_per_unit REAL,operating_hours REAL DEFAULT 1248,fault TEXT DEFAULT 'normal');
        CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY AUTOINCREMENT,machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,temperature REAL,vibration REAL,power REAL,timestamp TEXT);
        CREATE INDEX IF NOT EXISTS idx_reading_machine ON readings(machine_id,id);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,risk TEXT,message TEXT,created_at TEXT,acknowledged INTEGER DEFAULT 0,resolved_at TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,machine_id TEXT REFERENCES machines(id) ON DELETE CASCADE,title TEXT,priority TEXT,due_date TEXT,status TEXT,created_at TEXT,completed_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        ''')
        if not con.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
            for seed in SEEDS:
                con.execute('INSERT INTO machines(id,name,zone,type,baseline_power,units_per_hour,profit_per_unit) VALUES(?,?,?,?,?,?,?)',seed)
            con.execute("UPDATE machines SET fault='warning' WHERE id='M-02'")
            con.execute("UPDATE machines SET fault='critical' WHERE id='M-04'")
            for raw in con.execute('SELECT * FROM machines').fetchall():
                m = dict(raw)
                for step in range(36):
                    ts = datetime.fromtimestamp(time.time()-(35-step)*5,timezone.utc).isoformat()
                    write_reading(con,m,reading(m,step,m['fault'] if step>28 else 'normal'),ts)
            con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('task-seed','M-02','Inspect press bearing alignment','High',datetime.now(timezone.utc).date().isoformat(),'Scheduled',now(),None))
            con.execute("INSERT INTO settings VALUES('initialized','true')")

# Simulation advances once per server tick, never once per connected client.
def tick():
    with db() as con:
        for raw in con.execute('SELECT * FROM machines').fetchall():
            m = dict(raw)
            write_reading(con,m,reading(m,time.time()/5,m['fault']),now())
            con.execute('UPDATE machines SET operating_hours=operating_hours+? WHERE id=?',(5/3600,m['id']))

async def loop():
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(tick)

@asynccontextmanager
async def lifespan(app):
    initialize()
    task = asyncio.create_task(loop()) if SIMULATE else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

app = FastAPI(title='FactoryGuard AI API',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.environ.get('FACTORYGUARD_ORIGINS','http://localhost:3000').split(',') if x.strip()],allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-API-Key'])

def authorize(x_api_key: str | None = Header(default=None)):
    key = os.environ.get('FACTORYGUARD_API_KEY','')
    if key and not secrets.compare_digest(key,x_api_key or ''):
        raise HTTPException(401,'A valid demo API key is required.')

class MachineInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    name: str = Field(min_length=2,max_length=80)
    zone: str = Field(min_length=2,max_length=50)
    type: str = Field(min_length=2,max_length=40)
    baseline_power: float = Field(gt=0,le=10000)
    units_per_hour: float = Field(ge=0,le=1000000)
    profit_per_unit: float = Field(ge=0,le=10000000)

class TaskInput(BaseModel):
    machine_id: str
    title: str = Field(min_length=3,max_length=160)
    priority: Literal['Low','Medium','High'] = 'Medium'
    due_date: str
    status: Literal['Scheduled','In progress','Completed'] = 'Scheduled'
    def validated_date(self):
        try:
            datetime.strptime(self.due_date,'%Y-%m-%d')
        except ValueError:
            raise HTTPException(422,'due_date must be YYYY-MM-DD')

class LossInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    downtime_hours: float = Field(ge=0,le=8760)
    units_per_hour: float = Field(ge=0,le=1000000)
    profit_per_unit: float = Field(ge=0,le=10000000)
    repair_cost: float = Field(ge=0,le=1000000000)

class ScenarioInput(BaseModel):
    machine_id: str
    scenario: Literal['normal','warning','critical']

class Question(BaseModel):
    question: str = Field(min_length=1,max_length=1000)

class ReadingInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    temperature: float = Field(ge=-50,le=500)
    vibration: float = Field(ge=0,le=100)
    power: float = Field(ge=0,le=10000)

def get_machine(con,id):
    row=con.execute('SELECT * FROM machines WHERE id=?',(id,)).fetchone()
    if not row:
        raise HTTPException(404,'Machine not found')
    return dict(row)

def machines_data(con):
    data=[]
    for raw in con.execute('SELECT * FROM machines ORDER BY id').fetchall():
        m=dict(raw)
        r=dict(con.execute('SELECT * FROM readings WHERE machine_id=? ORDER BY id DESC LIMIT 1',(m['id'],)).fetchone())
        m.update(reading=r,analysis=analyze(m,r))
        data.append(m)
    return data

def loss_data(con):
    row=con.execute("SELECT value FROM settings WHERE key='loss'").fetchone()
    assumptions=json.loads(row['value']) if row else {'downtime_hours':4,'units_per_hour':180,'profit_per_unit':95,'repair_cost':12000}
    return {**assumptions,**loss(**assumptions)}

def summary(con,machines):
    healthy=sum(m['analysis']['risk']=='Low' for m in machines)
    warning=sum(m['analysis']['risk']=='Medium' for m in machines)
    sample=con.execute('SELECT count(*) n,coalesce(sum(temperature<95 AND vibration<7.1),0) safe FROM readings').fetchone()
    return {'total':len(machines),'healthy':healthy,'warning':warning,'critical':len(machines)-healthy-warning,'active_alerts':con.execute('SELECT count(*) FROM alerts WHERE resolved_at IS NULL').fetchone()[0], 'uptime':round(100*sample['safe']/max(1,sample['n']),1),'uptime_label':'Simulated availability across retained samples','health':round(sum(m['analysis']['health'] for m in machines)/max(1,len(machines))), 'power':round(sum(m['reading']['power'] for m in machines),1)}

@app.get('/api/health')
def health():
    return {'status':'ok','simulated':True,'engine':'Isolation Forest + rules' if MODEL else 'Threshold rules','history_limit':HISTORY}

@app.get('/api/state',dependencies=[Depends(authorize)])
def state():
    with db() as con:
        machines=machines_data(con)
        return {'machines':machines,'alerts':[dict(r) for r in con.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT 300')],'tasks':[dict(r) for r in con.execute('SELECT * FROM tasks ORDER BY created_at DESC')],'loss':loss_data(con),'analytics':summary(con,machines),'timestamp':now(),'mode':'api','simulated':True}

@app.get('/api/machines',dependencies=[Depends(authorize)])
def list_machines():
    with db() as con:
        return machines_data(con)

@app.post('/api/machines',status_code=201,dependencies=[Depends(authorize)])
def add_machine(item:MachineInput):
    m={'id':'M-'+uuid.uuid4().hex[:6].upper(),**item.model_dump(),'fault':'normal'}
    with db() as con:
        con.execute('INSERT INTO machines(id,name,zone,type,baseline_power,units_per_hour,profit_per_unit) VALUES(:id,:name,:zone,:type,:baseline_power,:units_per_hour,:profit_per_unit)',m)
        write_reading(con,m,reading(m,0),now())
    return m

@app.put('/api/machines/{id}',dependencies=[Depends(authorize)])
def edit_machine(id:str,item:MachineInput):
    with db() as con:
        m=get_machine(con,id)
        con.execute('UPDATE machines SET name=:name,zone=:zone,type=:type,baseline_power=:baseline_power,units_per_hour=:units_per_hour,profit_per_unit=:profit_per_unit WHERE id=:id',{'id':id,**item.model_dump()})
        m.update(item.model_dump())
        write_reading(con,m,reading(m,time.time()/5,m['fault']),now())
    return m

@app.delete('/api/machines/{id}',dependencies=[Depends(authorize)])
def delete_machine(id:str):
    with db() as con:
        get_machine(con,id)
        con.execute('DELETE FROM machines WHERE id=?',(id,))
    return {'deleted':id}

@app.get('/api/machines/{id}/readings',dependencies=[Depends(authorize)])
def history(id:str):
    with db() as con:
        get_machine(con,id)
        return [dict(r) for r in con.execute('SELECT * FROM readings WHERE machine_id=? ORDER BY id DESC LIMIT ?',(id,HISTORY))][::-1]

@app.post('/api/machines/{id}/readings',dependencies=[Depends(authorize)])
def ingest(id:str,item:ReadingInput):
    with db() as con:
        m=get_machine(con,id)
        write_reading(con,m,item.model_dump(),now())
        return analyze(m,item.model_dump())

@app.get('/api/machines/{id}/analysis',dependencies=[Depends(authorize)])
def analysis(id:str):
    with db() as con:
        m=get_machine(con,id)
        r=con.execute('SELECT * FROM readings WHERE machine_id=? ORDER BY id DESC LIMIT 1',(id,)).fetchone()
        return analyze(m,dict(r))

@app.post('/api/simulation/scenario',dependencies=[Depends(authorize)])
def scenario(item:ScenarioInput):
    with db() as con:
        m=get_machine(con,item.machine_id)
        con.execute('UPDATE machines SET fault=? WHERE id=?',(item.scenario,item.machine_id))
        r=reading(m,time.time()/5,item.scenario)
        write_reading(con,m,r,now())
        return analyze(m,r)

@app.get('/api/alerts',dependencies=[Depends(authorize)])
def alerts():
    with db() as con:
        return [dict(r) for r in con.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT 300')]

@app.post('/api/alerts/{id}/acknowledge',dependencies=[Depends(authorize)])
def acknowledge(id:int):
    with db() as con:
        if con.execute('UPDATE alerts SET acknowledged=1 WHERE id=?',(id,)).rowcount==0:
            raise HTTPException(404,'Alert not found')
    return {'acknowledged':id}

@app.get('/api/tasks',dependencies=[Depends(authorize)])
def tasks():
    with db() as con:
        return [dict(r) for r in con.execute('SELECT * FROM tasks ORDER BY created_at DESC')]

@app.post('/api/tasks',status_code=201,dependencies=[Depends(authorize)])
def add_task(item:TaskInput):
    item.validated_date()
    t={'id':uuid.uuid4().hex,**item.model_dump(),'created_at':now(),'completed_at':now() if item.status=='Completed' else None}
    with db() as con:
        get_machine(con,item.machine_id)
        con.execute('INSERT INTO tasks VALUES(:id,:machine_id,:title,:priority,:due_date,:status,:created_at,:completed_at)',t)
    return t

@app.put('/api/tasks/{id}',dependencies=[Depends(authorize)])
def update_task(id:str,item:TaskInput):
    item.validated_date()
    with db() as con:
        get_machine(con,item.machine_id)
        old=con.execute('SELECT * FROM tasks WHERE id=?',(id,)).fetchone()
        if not old:
            raise HTTPException(404,'Task not found')
        t={'id':id,**item.model_dump(),'completed_at':(old['completed_at'] or now()) if item.status=='Completed' else None}
        con.execute('UPDATE tasks SET machine_id=:machine_id,title=:title,priority=:priority,due_date=:due_date,status=:status,completed_at=:completed_at WHERE id=:id',t)
    return t

@app.post('/api/loss',dependencies=[Depends(authorize)])
def calculate(item:LossInput):
    with db() as con:
        con.execute("INSERT INTO settings VALUES('loss',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(item.model_dump_json(),))
    return {**item.model_dump(),**loss(**item.model_dump())}

@app.get('/api/analytics',dependencies=[Depends(authorize)])
def analytics():
    with db() as con:
        return summary(con,machines_data(con))

@app.post('/api/assistant',dependencies=[Depends(authorize)])
def assistant(item:Question):
    with db() as con:
        return {'answer':answer(item.question,machines_data(con),[dict(r) for r in con.execute('SELECT * FROM tasks')],loss_data(con)),'engine':'Context-aware intent rules; no external LLM'}

@app.get('/api/reports/{kind}',dependencies=[Depends(authorize)])
def report(kind:Literal['machines','alerts','maintenance','loss']):
    with db() as con:
        if kind=='machines':
            rows=[{'id':m['id'],'name':m['name'],'zone':m['zone'],**{k:m['reading'][k] for k in ['temperature','vibration','power','timestamp']},'risk':m['analysis']['risk'],'explanation':' '.join(m['analysis']['reasons']),'simulated':True} for m in machines_data(con)]
        elif kind=='loss':
            rows=[loss_data(con)]
        else:
            rows=[dict(r) for r in con.execute('SELECT * FROM '+('tasks' if kind=='maintenance' else 'alerts'))]
        stream=io.StringIO()
        fields=list(rows[0]) if rows else ['id','message']
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Neutralize spreadsheet formulas in user-provided strings.
            writer.writerow({k:("'"+v if isinstance(v,str) and v[:1] in ['=','+','-','@','\t','\r'] else v) for k,v in row.items()})
    return Response('\ufeff'+stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="factoryguard-{kind}.csv"'})

# Optional single-origin cloud deployment: build frontend, then run this app.
DIST=Path(__file__).parents[1]/'dist'
if DIST.exists():
    app.mount('/',StaticFiles(directory=DIST,html=True),name='frontend')
