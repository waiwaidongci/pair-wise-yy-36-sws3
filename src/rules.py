from __future__ import annotations
from .domain import ConflictError, ValidationError
TITLE='企业排污许可与超标处置'; ENTITY='排污事件'; ID_PREFIX='ED'
SEVERITIES=['normal', 'watch', 'exceedance', 'major']; STATES=['reported', 'assessing', 'remediation', 'inspection', 'closed']; TRANSITIONS={'reported': ['assessing'], 'assessing': ['remediation'], 'remediation': ['inspection'], 'inspection': ['closed'], 'closed': []}; TRANSITION_ROLES={'assessing': ['compliance_officer'], 'remediation': ['operator'], 'inspection': ['compliance_officer'], 'closed': ['director']}
CREATE_ROLES=set(['operator', 'compliance_officer']); RECORD_ROLES=set(['operator', 'compliance_officer']); AUDIT_ROLES=set(['director', 'viewer']); VIEW_ROLES=set(['operator', 'compliance_officer', 'director', 'viewer'])
SEVERITY_WEIGHT={'normal': 1.0, 'watch': 3.0, 'exceedance': 6.0, 'major': 9.0}; DEADLINE_HOURS={'normal': 72, 'watch': 24, 'exceedance': 8, 'major': 4}; TERMINAL_STATES=set(['closed'])
INSPECTION_STAGE='inspection'; INSPECTION_STATUSES=['pending', 'completed', 'deferred']; INSPECTION_CONCLUSIONS=['passed', 'exceedance_found']; INSPECTION_RETURN_STATE='remediation'; INSPECTION_ROLES=set(['compliance_officer'])
def priority_score(severity,quantity=0.0,threshold=1.0,open_records=0):
    if severity not in SEVERITY_WEIGHT: raise ValidationError("unknown severity")
    ratio=quantity/threshold if threshold>0 else 1.0
    return max(0,min(10,int(round(SEVERITY_WEIGHT[severity]+min(4.0,ratio*4.0)+min(3.0,float(open_records))))))
def response_deadline_hours(severity,quantity=0.0,threshold=1.0):
    if severity not in DEADLINE_HOURS: raise ValidationError("unknown severity")
    ratio=quantity/threshold if threshold>0 else 1.0
    return max(1,int(DEADLINE_HOURS[severity]/max(1.0,ratio)))
def escalation_required(severity,quantity=0.0,threshold=1.0):
    return severity==SEVERITIES[-1] or (threshold>0 and quantity>=threshold)
def can_transition(current,target): return target in TRANSITIONS.get(current,[])
def validate_transition(current,target):
    if current not in STATES or target not in STATES: raise ValidationError("未知状态")
    if not can_transition(current,target): raise ConflictError(f"不能从{current}转换到{target}")
def ensure_inspection_stage(status):
    if status!=INSPECTION_STAGE: raise ConflictError("事件不在复查阶段，不能登记检查")
def normalize_conclusion(value):
    if value not in INSPECTION_CONCLUSIONS: raise ValidationError("conclusion不在允许范围内")
    return value
def validate_new_exceedance(quantity,threshold):
    if threshold>0 and quantity<threshold: raise ValidationError("最新浓度未超过许可限值，不能判定超标")
def validate_deferral(inspection_date,recheck_date):
    if recheck_date<inspection_date: raise ValidationError("复检日期不能早于检查日期")
def inspection_blockers(latest_inspection):
    if latest_inspection is None: return ["尚无现场检查记录"]
    status=latest_inspection.get("status")
    if status=="pending": return ["最近检查未完成"]
    if status=="deferred": return ["最近检查已暂缓，等待复检"]
    return []
def completion_blockers(target,open_records,latest_inspection=None):
    if target not in TERMINAL_STATES: return []
    blockers=inspection_blockers(latest_inspection)
    if open_records>0: blockers.append("仍有未关闭事项")
    return blockers
def role_for_transition(target): return set(TRANSITION_ROLES.get(target,[]))
