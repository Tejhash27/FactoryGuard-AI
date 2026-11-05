"""Synthetic telemetry and explainable anomaly analysis; never a failure probability."""
import json
import math
import random
from pathlib import Path

CONFIG = json.loads((Path(__file__).parents[1] / 'frontend/src/config.json').read_text())
MODEL = None
try:
    from sklearn.ensemble import IsolationForest
    rng = random.Random(27)
    training = [[rng.gauss(64, 5), max(.1, rng.gauss(2.2, .5)), rng.gauss(1, .06)] for _ in range(480)]
    MODEL = IsolationForest(n_estimators=64, contamination=.025, random_state=27, n_jobs=1).fit(training)
except ImportError:
    pass

SEEDS = [
    ('M-01','CNC Milling Center','Machining','CNC',18,220,140),
    ('M-02','Hydraulic Press','Forming','Press',24,180,95),
    ('M-03','Assembly Conveyor','Assembly','Conveyor',6,420,38),
    ('M-04','Industrial Compressor','Utilities','Compressor',32,150,72),
    ('M-05','Robotic Welding Cell','Fabrication','Robot',15,260,110),
]

def reading(machine, step, fault=None):
    phase = step * .47 + sum(map(ord,machine['id']))
    temp = 64 + 4 * math.sin(phase)
    vib = 2.2 + .35 * math.sin(phase*1.3)
    power = machine['baseline_power'] * (1 + .04 * math.cos(phase))
    if fault == 'warning':
        temp, vib = 84 + math.sin(phase), 5.3 + .2 * math.sin(phase)
    elif fault == 'critical':
        temp, vib = 99 + math.sin(phase), 8.6 + .2 * math.sin(phase)
        power *= 1.54
    return {'temperature':round(temp,1),'vibration':round(vib,2),'power':round(power,2)}

def analyze(machine, r, use_model=True):
    reasons, actions, level = [], [], 0
    for key, label, action in [('temperature','Temperature','Inspect cooling, coolant flow and lubrication.'),('vibration','Vibration','Inspect bearings, alignment and loose mounts.'),('power','Power consumption','Inspect motor load and electrical connections.')]:
        value = r[key]
        compare = value/machine['baseline_power'] if key == 'power' else value
        threshold = CONFIG[key]
        severity = 2 if compare >= threshold['critical'] else 1 if compare >= threshold['warning'] else 0
        if severity:
            limit = threshold['critical' if severity==2 else 'warning'] * (machine['baseline_power'] if key=='power' else 1)
            reasons.append(f"{label} {value:g} {threshold['unit']} exceeds the {'critical' if severity==2 else 'warning'} threshold {limit:g} {threshold['unit']}.")
            actions.append(action)
            level = max(level,severity)
    score = None
    if use_model and MODEL is not None:
        features = [[r['temperature'],r['vibration'],r['power']/machine['baseline_power']]]
        score = round(float(MODEL.decision_function(features)[0]),4)
        if score < 0 and level == 0:
            level = 1
            reasons.append('The combined readings differ from the synthetic normal training baseline.')
            actions.append('Review the recent sensor trend and verify sensor calibration.')
    if not reasons:
        reasons = ['All readings are inside the illustrative operating thresholds.']
        actions = ['Continue routine monitoring and scheduled inspection.']
    return {'risk':['Low','Medium','High'][level], 'status':['Healthy','Warning','Critical'][level], 'health':[96,62,24][level], 'reasons':reasons,'recommendations':actions,'model': 'Isolation Forest + threshold rules' if use_model and MODEL is not None else 'Transparent threshold rules','anomaly_score':score,'disclaimer':'Synthetic demonstration; anomaly score is not a failure probability. Health is a rule-based index, not remaining useful life.'}

def loss(downtime_hours,units_per_hour,profit_per_unit,repair_cost):
    production = round(downtime_hours*units_per_hour*profit_per_unit,2)
    return {'production_loss':production,'repair_cost':repair_cost,'total_impact':round(production+repair_cost,2),'currency':'INR','estimated':True}

def answer(question,machines,tasks,impact):
    if not machines:
        return 'No machines are registered. Add a machine in Monitoring to begin.'
    q = question.lower()
    selected = next((m for m in machines if m['id'].lower() in q or m['name'].lower() in q or ('machine '+m['id'][-2:]) in q),None)
    worst = min(machines,key=lambda m:m['analysis']['health'])
    if any(w in q for w in ['loss','impact','cost','rupee']):
        return f"The estimated production loss is ₹{impact['production_loss']:,.2f}; including repair costs, total impact is ₹{impact['total_impact']:,.2f}. These are scenario assumptions from the Loss Calculator, not measured losses."
    if selected or any(w in q for w in ['why','abnormal','highest','risk','action']):
        m = selected or worst
        a = m['analysis']
        return f"{m['id']} · {m['name']} has {a['risk'].lower()} risk. {' '.join(a['reasons'])} Recommended inspection: {' '.join(a['recommendations'])} This is simulated telemetry, not a confirmed fault diagnosis."
    if any(w in q for w in ['maintenance','task','need']):
        flagged = [m['id']+' '+m['name'] for m in machines if m['analysis']['risk']!='Low']
        return f"{'Inspect '+', '.join(flagged) if flagged else 'No machines exceed the current demo thresholds'}. There are {sum(t['status']!='Completed' for t in tasks)} open maintenance tasks. Create or schedule a task in Maintenance."
    return 'I can explain a machine’s current readings, identify the highest risk, list maintenance needs or summarize the estimated financial impact. Try “Why is Machine 02 abnormal?”'
