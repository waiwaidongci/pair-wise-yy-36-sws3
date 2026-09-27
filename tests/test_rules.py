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
    def test_inspection_judgement(self):
        self.assertEqual(rules.inspection_status_for('deferred'),'pending')
        self.assertEqual(rules.inspection_status_for('passed'),'completed')
        self.assertEqual(rules.rollback_target('exceeded'),'remediation')
        self.assertIsNone(rules.rollback_target('passed'))
    def test_closure_blockers(self):
        self.assertEqual(rules.completion_blockers('remediation',3,None),[])
        self.assertIn("尚未登记现场检查",rules.completion_blockers('closed',0,None))
        self.assertTrue(any("检查" in b for b in rules.completion_blockers('closed',0,{"status":"pending"})))
        self.assertEqual(rules.completion_blockers('closed',0,{"status":"completed"}),[])
        self.assertTrue(any("未关闭" in b for b in rules.completion_blockers('closed',2,{"status":"completed"})))
if __name__=="__main__": unittest.main()
