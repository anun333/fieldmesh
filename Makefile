# fieldmesh — layer zero
.POSIX:
.PHONY: help pages test demo world drill siting forecast irrigation q5 q5-points power vocab vocab-resolve packs serve season export frost clean

help:
	@echo "test   run every test (sdk + tools + sim + server + modules)"
	@echo "demo   log -> derived state -> SensorThings, no hardware"
	@echo "world  a day of farm physics through a node to the gateway"
	@echo "drill  seed faults and score the detectors against ground truth"
	@echo "siting score the depth check against moves nobody logged (§4.1)"
	@echo "forecast  forecasts through layer zero on real 2007 weather, scored (Q26)"
	@echo "irrigation  watering by timer, forecast and soil probe on a recorded summer"
	@echo "q5     the encoding measurement behind the Q5 decision"
	@echo "q5-points  what each encoding costs at realistic sample/transmit rates"
	@echo "power  where a node's battery goes, per datastream"
	@echo "vocab  every observed-property term, its source and its unit"
	@echo "vocab-resolve  fetch every registered term (needs a connection)"
	@echo "packs  language packs: coverage, soundness (docs/LANGUAGE_PACKS.md)"
	@echo "serve  a SensorThings 1.1 endpoint over a simulated farm"
	@echo "season how long a 180-day season takes to simulate"
	@echo "export a season out in open formats, then verify it replays (§7.6)"
	@echo "frost  stand up FROST-Server as a conformance oracle"
	@echo "pages  build the project site into _site/ (needs markdown-it-py)"
	@echo "clean  remove __pycache__"

test:
	@cd sdk && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd tools && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd sim && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd server && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/advise && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/rules && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/water && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/soilwater && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/zoneflow && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/sowing && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/twin && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/notify && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd modules/board && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q

demo:
	@cd sdk && python3 demo.py

world:
	@cd sim && python3 world_demo.py

drill:
	@cd sim && python3 drill.py --compare

siting:
	@cd sim && python3 siting_drill.py

forecast:
	@cd sim && python3 forecast_drill.py

irrigation:
	@cd sim && python3 irrigation_drill.py

q5:
	@cd tools && python3 q5_encoding.py

q5-points:
	@cd tools && python3 q5_encoding.py --operating-points

power:
	@cd tools && python3 power_budget.py

vocab:
	@cd sdk && python3 vocab.py

vocab-resolve:
	@cd sdk && python3 vocab.py --resolve

packs:
	@cd tools && python3 packs.py

serve:
	@cd server && python3 serve.py --days $${DAYS:-2} --open

season:
	@cd sim && python3 -c "import time, harrow_bend as hb; \
		f=hb.build(); t=time.perf_counter(); hb.season(f, days=$${DAYS:-180}); \
		e=time.perf_counter()-t; print(f'{e:.1f}s for $${DAYS:-180} days '\
		f'({e/$${DAYS:-180}:.2f}s/day, {len(f.state.observations)} observations)')"

export:
	@cd sim && python3 export_demo.py --days $${DAYS:-7}

frost:
	@echo "See docs/notes/frost-validation.md for the two-container recipe."

pages:
	@python3 tools/pages.py _site

clean:
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
