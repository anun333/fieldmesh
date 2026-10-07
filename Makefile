# librefarm — layer zero
.POSIX:
.PHONY: help test demo q5 q5-points power frost clean

help:
	@echo "test   run every test (sdk + tools)"
	@echo "demo   log -> derived state -> SensorThings, no hardware"
	@echo "q5     the encoding measurement behind the Q5 decision"
	@echo "q5-points  what each encoding costs at realistic sample/transmit rates"
	@echo "power  where a node's battery goes, per datastream"
	@echo "frost  stand up FROST-Server as a conformance oracle"
	@echo "clean  remove __pycache__"

test:
	@cd sdk && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q
	@cd tools && python3 -W error::ResourceWarning -m unittest discover -p 'test_*.py' -q

demo:
	@cd sdk && python3 demo.py

q5:
	@cd tools && python3 q5_encoding.py

q5-points:
	@cd tools && python3 q5_encoding.py --operating-points

power:
	@cd tools && python3 power_budget.py

frost:
	@echo "See docs/notes/frost-validation.md for the two-container recipe."

clean:
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
