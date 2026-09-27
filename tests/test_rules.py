import unittest
from src import rules
from src.domain import ConflictError, ValidationError
class RulesTest(unittest.TestCase):
    def test_priority_deadline_and_escalation(self):
        low=rules.priority_score(rules.SEVERITIES[0],1,10,0); high=rules.priority_score(rules.SEVERITIES[-1],30,10,3)
        self.assertGreater(high,low); self.assertLessEqual(rules.response_deadline_hours(rules.SEVERITIES[-1],30,10),rules.response_deadline_hours(rules.SEVERITIES[0],1,10))
        self.assertTrue(rules.escalation_required(rules.SEVERITIES[-1],1,10)); self.assertTrue(rules.escalation_required(rules.SEVERITIES[0],10,10))
    def test_transition_guards(self):
        self.assertTrue(rules.can_transition(rules.STATES[0],rules.STATES[1]))
        with self.assertRaises(ConflictError): rules.validate_transition(rules.STATES[0],rules.STATES[-1])
        with self.assertRaises(ValidationError): rules.priority_score("not-a-severity",1,1)
    def test_inspection_rules(self):
        self.assertEqual(rules.inspection_blockers(None),["尚无现场检查记录"])
        self.assertEqual(rules.inspection_blockers({"status":"pending"}),["最近检查未完成"])
        self.assertEqual(rules.inspection_blockers({"status":"deferred"}),["最近检查已暂缓，等待复检"])
        self.assertEqual(rules.inspection_blockers({"status":"completed"}),[])
        self.assertEqual(rules.completion_blockers("closed",2,{"status":"completed"}),["仍有未关闭事项"])
        self.assertEqual(rules.completion_blockers("remediation",5,None),[])
        with self.assertRaises(ConflictError): rules.ensure_inspection_stage("remediation")
        with self.assertRaises(ValidationError): rules.normalize_conclusion("unknown")
        with self.assertRaises(ValidationError): rules.validate_new_exceedance(3,10)
        with self.assertRaises(ValidationError): rules.validate_deferral("2026-09-27","2026-09-26")
if __name__=="__main__": unittest.main()
