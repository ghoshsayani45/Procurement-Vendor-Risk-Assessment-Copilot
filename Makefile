.PHONY: setup ground-truth policies synthetic ingest corpus eval-set grade retrieval-baseline prompt-baseline prompt-baseline-mock test schemas up down

setup:            ## create venv and install dependencies
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

ground-truth:     ## step 1.3: rebuild 35 vendors + expected outcomes (fails on any inconsistency)
	python -m scripts.build_vendors

policies:         ## step 1.4a: render internal policy documents from rubric.yaml
	python -m scripts.generate_policies

synthetic:        ## step 1.4b: render synthetic vendor documents and validate their facts
	python -m scripts.generate_synthetic_docs

ingest:           ## step 1.4c: extract real sources per the source register + merge synthetic -> corpus_v1
	python -m scripts.ingest

corpus: ground-truth policies synthetic ingest   ## full rebuild of corpus v1

eval-set:         ## step 1.5: rebuild eval_v1 (DON'T run after the freeze; create eval_v2 instead)
	python -m scripts.build_eval_set

grade:            ## grade predictions: make grade PRED=runs/dev.jsonl SPLIT=dev
	python -m scripts.grade $(PRED) --split $(or $(SPLIT),dev)

retrieval-baseline: ## step 1.8: BM25 (+ dense with RETRIEVERS=bm25,dense) on eval_v1 gold docs + ACORD
	python -m scripts.retrieval_baseline --retrievers $(or $(RETRIEVERS),bm25)

prompt-baseline:  ## steps 1.6-1.7: 3 prompting strategies on the dev split via the course endpoint (uses token quota)
	python -m scripts.prompt_baseline --split dev

prompt-baseline-mock: ## offline pipeline check with a stand-in model (numbers meaningless; reports/mock/ only)
	LLM_BACKEND=mock python -m scripts.prompt_baseline --split dev

schemas:
	python -m scripts.export_json_schemas

test:
	python -m pytest -q

up:
	docker compose -f docker/docker-compose.yml --env-file .env up -d

down:
	docker compose -f docker/docker-compose.yml --env-file .env down
