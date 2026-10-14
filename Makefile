.PHONY: install seed test validate serve demo lint
install:
	python -m pip install -e '.[dev]'
seed:
	python -m ossie_demo seed
validate:
	python -m ossie_demo validate
test:
	python -m pytest -q
serve:
	uvicorn ossie_demo.api:app --reload --host 127.0.0.1 --port 8000
demo:
	python -m ossie_demo ask 'Show total stake by country'
lint:
	ruff check ossie_demo tests
