# librefarm — layer zero
.POSIX:
.PHONY: help test demo world drill q5 q5-points power vocab serve season frost clean

help:
	@echo "test   run every test (sdk + tools + sim + server)"
	@echo "demo   log -> derived state -> SensorThings, no hardware"
	@echo "world  a day of farm physics through a node to the gateway"
	@echo "drill  seed faults and score the detectors against ground truth"
	@echo "q5     the encoding measurement behind the Q5 decision"
	@echo "q5-points  what each encoding costs at realistic sample/transmit rates"
	@echo "power  where a node's battery goes, per datastream"
	@echo "vocab  every observed-property term, its source and its unit"
	@echo "serve  a SensorThings 1.1 endpoint over a simulated farm"
	@echo "season how long a 180-day season takes to simulate"
	@echo "frost  stand up FROST-Server as a conformance oracle"
	@echo "clean  remove __pycache__"

test:
	@cd sdk && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd tools && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd sim && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd server && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q

demo:
	@cd sdk && python3 demo.py

world:
	@cd sim && python3 world_demo.py

drill:
	@cd sim && python3 drill.py --compare

q5:
	@cd tools && python3 q5_encoding.py

q5-points:
	@cd tools && python3 q5_encoding.py --operating-points

power:
	@cd tools && python3 power_budget.py

vocab:
	@cd sdk && python3 vocab.py

serve:
	@cd server && python3 serve.py --days $${DAYS:-2}

season:
	@cd sim && python3 -c "import time, harrow_bend as hb; \
		f=hb.build(); t=time.perf_counter(); hb.season(f, days=$${DAYS:-180}); \
		e=time.perf_counter()-t; print(f'{e:.1f}s for $${DAYS:-180} days '\
		f'({e/$${DAYS:-180}:.2f}s/day, {len(f.state.observations)} observations)')"

frost:
	@echo "See docs/notes/frost-validation.md for the two-container recipe."

clean:
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
