"""Read service health and non-sensitive recent event/error counters."""
import json
from tools.deploy_stage4_economy import remote

CODE=r'''
import collections,json,re,subprocess
state=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ExecMainStatus','-p','ActiveState'],text=True)
lines=subprocess.check_output(['journalctl','-u','tio-server','--since','10 minutes ago','--no-pager','-o','cat'],text=True).splitlines()
events=collections.Counter();errors=collections.Counter();locations=[]
for line in lines:
 try:
  value=json.loads(line)
  if isinstance(value,dict):
   event=value.get('event')
   if isinstance(event,str) and re.fullmatch('[a-z_0-9-]{1,64}',event):events[event]+=1
 except ValueError:pass
 match=re.match(r'^((?:[A-Za-z][A-Za-z0-9_]*\.)*[A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):',line)
 if match:errors[match[1]]+=1
 if re.match(r'^\s*File "/opt/tio-emulator/(?:server|tio|tools)/[A-Za-z0-9_/.]+", line \d+, in [A-Za-z_0-9]+$',line):locations.append(line.strip())
print(json.dumps(dict(service=state.strip(),events=dict(events),errors=dict(errors),traceback_locations=locations[-12:],raw_packets_printed=False)))
'''
if __name__=='__main__':print(json.dumps(remote(CODE,{})))
