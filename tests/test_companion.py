import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('companion',Path(__file__).parents[1]/'scripts/companion.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def event(kind,turn='t1'):
    return {'timestamp':dt.datetime.now(dt.timezone.utc).isoformat(), 'type':'event_msg', 'payload':{'type':kind,'turn_id':turn}}

class Tests(unittest.TestCase):
    def test_quota_windows_and_unknown(self):
        q=m.quotas({'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':61,'windowDurationMins':10080,'resetsAt':None}}}})
        self.assertEqual(q[0][:2],(39,10080));self.assertEqual(q[1][0],-1)
        self.assertEqual(m.quotas({'rateLimitsByLimitId':{'spark':{}}})[0][0],-1)
        self.assertEqual(m.quotas({'rateLimits':{'limitId':'codex','primary':{'usedPercent':110,'windowDurationMins':300}}})[0][0],0)
    def test_baseline_dedup_abort_and_selection(self):
        with tempfile.TemporaryDirectory() as d:
            e=m.Events(d,thread_id='a')
            e.apply(event('task_complete','old'),'a',baseline=True)
            self.assertEqual(e.done,0)
            e.apply(event('task_started'),'a');self.assertEqual(len(e.active),1)
            done=event('task_complete');e.apply(done,'a');e.apply(done,'a')
            self.assertEqual(e.done,1);self.assertEqual(len(e.pending),1);self.assertFalse(e.active)
            e.apply(event('task_complete','foreign'),'b');self.assertEqual(e.done,1)
            e.apply(event('turn_aborted','stop'),'a');self.assertEqual(e.done,1);self.assertEqual(e.pending[-1][1],2)
    def test_partial_line_and_restart_suppression(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'session.jsonl'
            p.write_text(json.dumps({'type':'session_meta','payload':{'id':'a','source':'appServer'}})+'\n')
            e=m.Events(d)
            line=json.dumps(event('task_complete'))
            with p.open('a') as f:f.write(line[:30])
            e.poll();self.assertFalse(e.pending)
            with p.open('a') as f:f.write(line[30:]+'\n')
            e.poll();self.assertEqual(e.done,1)
            e.poll();self.assertEqual(e.done,1)
            self.assertEqual(m.Events(d).done,0)
    def test_title_transport_preserves_chinese_without_sending_content(self):
        title='连接设备并探索二次开发'
        bitmap=m.title_bitmap(title)
        self.assertEqual(len(bitmap),3200)
        self.assertTrue(any(bitmap))
        levels={value >> shift & 3 for value in bitmap for shift in (0,2,4,6)}
        self.assertEqual(levels,{0,1,2,3})
        self.assertEqual(m.title_bitmap(title),bitmap)
        self.assertNotEqual(bitmap,m.title_bitmap('另一项任务'))
        packets=m.title_packets(7,[('task-a',title),('task-b','Review workspace consistency')],'Done')
        self.assertEqual(len(packets),4)
        self.assertTrue(packets[0][0].startswith(b'CDXP|7|0|'))
        self.assertEqual(packets[-1][0],b'CDXL|7|2|END\n')
        self.assertTrue(all(len(packet)<7168 for packet,_ in packets))
        with self.assertRaises(ValueError):m.title_packets(7,[('x','title')]*17,'')

    def test_account_tokens_dates_missing_and_aggregation(self):
        self.assertEqual(m.token_activity({'dailyUsageBuckets':None}),('--','--','No data'))
        data={'dailyUsageBuckets':[{'startDate':'2026-09-01','tokens':1000}, {'startDate':'2026-09-06','tokens':2000}, {'startDate':'2026-09-07','tokens':3000}]}
        self.assertEqual(m.token_activity(data),('3K','6K','09/07'))
        data['dailyUsageBuckets'].append({'startDate':'2026-08-31','tokens':100000})
        self.assertEqual(m.token_activity(data)[1],'6K')
        self.assertEqual(m.token_activity({'dailyUsageBuckets':[{'startDate':'2026-09-07','tokens':0}]}),('0','--','09/07'))
        self.assertEqual(m.token_activity({'dailyUsageBuckets':[{'startDate':'bad','tokens':1}]}),('--','--','No data'))

    def test_task_elapsed_and_reported_completion_duration(self):
        with tempfile.TemporaryDirectory() as d:
            e=m.Events(d)
            start=event('task_started'); start['payload']['started_at']=m.time.time()-125
            e.apply(start,'a');self.assertGreaterEqual(e.elapsed('a'),125)
            finish=event('task_complete');finish['payload']['duration_ms']=123456
            e.apply(finish,'a');self.assertEqual(e.pending[-1],('a',1,123))
            self.assertEqual(e.elapsed('a'),-1)
            packet=m.metadata_frame(1,('1M','7M','09/06'),[('a',60)],123)
            self.assertIn(b'|123|1|',packet);self.assertEqual(len(packet.split(b'|')),9)

    def test_unchanged_files_are_not_reopened(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'session.jsonl'
            p.write_text(json.dumps({'type':'session_meta','payload':{'id':'a','source':'appServer'}})+'\n')
            e=m.Events(d);before=e.files_read
            for _ in range(10):e.poll()
            self.assertEqual(e.files_read,before)
            with p.open('a') as f:f.write(json.dumps(event('task_started'))+'\n')
            e.poll();self.assertEqual(e.files_read,before+1);self.assertIn('a',e.active)

    def test_project_raster_and_worktree_resolution(self):
        from unittest.mock import patch
        title='同名任务'
        self.assertNotEqual(m.title_bitmap(title,'Project A'),m.title_bitmap(title,'Project B'))
        packets=m.title_packets(8,[('a',title,'Project A')],'Done')
        self.assertEqual(len(packets),3)
        self.assertIn(b'CDXP|8|0|',packets[0][0])
        self.assertEqual(m.project_name(''),'No workspace')
        m.project_name.cache_clear()
        with patch.object(m.subprocess,'check_output',return_value='/work/original-project/.git\n') as call:
            self.assertEqual(m.project_name('/work/worktrees/abc/src'),'original-project')
            self.assertEqual(m.project_name('/work/worktrees/abc/src'),'original-project')
            self.assertEqual(call.call_count,1)
        with patch.object(m.subprocess,'check_output',side_effect=OSError):
            self.assertEqual(m.project_name('/work/plain-folder'),'plain-folder')
        m.project_name.cache_clear()

    def test_completion_title_and_workspace_have_separate_regions(self):
        title='完成任务详情页面的布局优化和中文显示'
        a=m.completion_bitmap(title,'项目甲');b=m.completion_bitmap(title,'项目乙')
        self.assertEqual(len(a),3200)
        split=168*60//4;end=168*76//4
        self.assertEqual(a[:split],b[:split]);self.assertNotEqual(a[split:end],b[split:end])
        self.assertEqual(a[end:],bytes(8));self.assertTrue(any(a[:split]));self.assertTrue(any(a[split:end]))
        first=m.title_packets(9,[],title,'项目甲')[0][0]
        second=m.title_packets(9,[],title,'项目乙')[0][0]
        self.assertNotEqual(first,second)
        self.assertLess(len(first),7168)

    def test_protocol_sanitizes_title(self):
        q=[(39,10080,'09/07 12:26'),(-1,0,'Not available')]
        packet=m.frame(1,q,2,1,1,True,'bad|\nname')
        self.assertEqual(len(packet.decode().strip().split('|')),14)
        self.assertEqual(packet.count(b'\n'),1)
        self.assertEqual(m.display_title('中文标题','1234567890'),'Task 34567890')

if __name__=='__main__':unittest.main()
