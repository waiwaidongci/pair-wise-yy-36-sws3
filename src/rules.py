from __future__ import annotations
from .domain import ConflictError, ValidationError
TITLE='企业排污许可与超标处置'; ENTITY='排污事件'; ID_PREFIX='ED'
SEVERITIES=['normal', 'watch', 'exceedance', 'major']; STATES=['reported', 'assessing', 'remediation', 'inspection', 'closed']; TRANSITIONS={'reported': ['assessing'], 'assessing': ['remediation'], 'remediation': ['inspection'], 'inspection': ['closed'], 'closed': []}; TRANSITION_ROLES={'assessing': ['compliance_officer'], 'remediation': ['operator'], 'inspection': ['compliance_officer'], 'closed': ['director']}
CREATE_ROLES=set(['operator', 'compliance_officer']); RECORD_ROLES=set(['operator', 'compliance_officer']); AUDIT_ROLES=set(['director', 'viewer']); VIEW_ROLES=set(['operator', 'compliance_officer', 'director', 'viewer']); INSPECT_ROLES=set(['compliance_officer'])
SEVERITY_WEIGHT={'normal': 1.0, 'watch': 3.0, 'exceedance': 6.0, 'major': 9.0}; DEADLINE_HOURS={'normal': 72, 'watch': 24, 'exceedance': 8, 'major': 4}; TERMINAL_STATES=set(['closed'])
DEFERRED_CONCLUSION='deferred'; EXCEEDED_CONCLUSION='exceeded'; RECHECK_CONCLUSIONS=set(['passed', 'exceeded']); ROLLBACK_STATE='remediation'
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
def inspection_status_for(conclusion): return 'pending' if conclusion==DEFERRED_CONCLUSION else 'completed'
def has_pending_inspection(latest_inspection): return latest_inspection is not None and latest_inspection.get("status")=='pending'
def needs_recheck_info(conclusion): return conclusion==DEFERRED_CONCLUSION
def rollback_target(conclusion): return ROLLBACK_STATE if conclusion==EXCEEDED_CONCLUSION else None
def closure_blockers(open_records,latest_inspection):
    blockers=[]
    if latest_inspection is None: blockers.append("尚未登记现场检查")
    elif latest_inspection.get("status")!='completed': blockers.append("最近检查尚未完成（暂缓待复检）")
    if open_records>0: blockers.append(f"仍有未关闭事项{open_records}笔")
    return blockers
def completion_blockers(target,open_records,latest_inspection=None): return closure_blockers(open_records,latest_inspection) if target in TERMINAL_STATES else []
def role_for_transition(target): return set(TRANSITION_ROLES.get(target,[]))
