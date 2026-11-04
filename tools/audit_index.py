from pathlib import Path
from astralogue.audit.store import AuditStore
from astralogue.audit.inventory import traverse
from astralogue.adapters.hf import write

if __name__=='__main__':
    with AuditStore() as s:write(Path('data/audit/inventory-report.json'),traverse(s,Path.cwd()))
    print('Full existing corpus traversal complete; see inventory-report.json')
