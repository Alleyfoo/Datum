"""Build a standalone offline HTML app with the Python evaluation fixture embedded."""
import json
from pathlib import Path
from datum_engine import all_scenarios
root = Path(__file__).resolve().parent
html = (root / 'app.template.html').read_text(encoding='utf-8')
seed = json.dumps(all_scenarios(), ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
(root / 'datum_visual_lab.html').write_text(html.replace('__DATA_JSON__', seed), encoding='utf-8')
print('Built', root / 'datum_visual_lab.html')
