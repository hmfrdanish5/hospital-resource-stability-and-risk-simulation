Pandemic Healthcare Stability Lab - Flask Dashboard
====================================================

SETUP
-----
  pip install -r ../requirements.txt
  python app.py
  Open http://127.0.0.1:5000

STRUCTURE
---------
  pandemic_dashboard/
  ├── app.py              Flask API (imports pandemic_bankers core)
  ├── templates/index.html
  └── static/
      ├── style.css       Clean academic light theme
      └── script.js       Config load, Banker's demo, Monte Carlo chart

API
---
  GET  /api/config        Default hospital configuration
  POST /bankers_demo      Deterministic Banker's analysis + step trace
  POST /run_simulation    Monte Carlo collapse-probability sweep

The dashboard delegates all algorithm logic to ../pandemic_bankers/.
