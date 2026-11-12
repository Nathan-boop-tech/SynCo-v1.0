# Synthra local training pipeline

This pipeline prepares reviewed examples and supports optional local LoRA
fine-tuning. It does not train automatically. The default base model is
`Qwen/Qwen2.5-Coder-1.5B-Instruct`; set `BASE_MODEL` to another compatible
open-weight model when needed. Model weights are downloaded only when you
explicitly run training without `--dry-run`.

## Example files

`examples.jsonl`, `validation.jsonl`, and the generated `train.jsonl` use one
JSON object per line with non-empty string fields:

```json
{"instruction":"Explain the change","input":"Add a timeout option","output":"Plan: inspect the client..."}
```

Add reviewed examples to `examples.jsonl`. Keep requests and outputs free of
credentials and personal data. Dataset preparation also imports approved
records from `feedback/good_examples.jsonl`, filters recognizable credential
patterns and malformed records, removes duplicates, and makes a reproducible
90/10 split using seed 42. Preparation overwrites `train.jsonl` and
`validation.jsonl`; it reports counts and average input/output lengths.

Inspect the generated JSONL before training. Check that outputs are accurate,
safe, consistent with Synthra's approval rules, and representative of tasks you
want to improve. Remove examples with contradictory instructions or sensitive
content.

## Commands

From the repository root:

```bash
python training/prepare_dataset.py
python training/train_lora.py --dry-run
python training/train_lora.py
python training/evaluate_model.py
python training/export_to_ollama.py
```

Dry-run validates both prepared datasets and prints their sizes and estimated
settings. It does not import model-loading code, download weights, or train.
Real training is opt-in and requires installing
`python -m pip install -r training/requirements.txt`. GPU memory and a
compatible PyTorch build are needed for practical training; a GPU or rented GPU
is typically required.

Training settings can be overridden with `BASE_MODEL`, `TRAIN_FILE`,
`VALIDATION_FILE`, `OUTPUT_DIR`, `MAX_STEPS`, `LEARNING_RATE`, and `BATCH_SIZE`.
Defaults are listed in `config.yaml`. LoRA rank, alpha, and dropout also accept
`LORA_RANK`, `LORA_ALPHA`, and `LORA_DROPOUT`.

The adapter is saved to `adapters/synthra-lora` by default, with logs at
`adapters/synthra-lora/training.log`. Training examples and validation examples
are both used by the trainer; validation data is for measuring held-out
behavior and is not mixed into gradient updates.

## Evaluation and Ollama export

The evaluation script sends each task to the current local Ollama model selected
by `SYNTHRA_MODEL` and writes per-task heuristic checks and an aggregate score
to `evaluation_results.json`. These simple text checks are not a substitute for
human review or behavioral tests.

Before Ollama can load a LoRA result, merge the adapter with the exact base
model used for training, for example by loading the base with Transformers,
loading the adapter with `PeftModel.from_pretrained`, calling
`merge_and_unload()`, and saving the merged model. Convert or install the merged
weights in a format supported by the installed Ollama version. The export
script writes a Modelfile with a placeholder `FROM` path; replace it with the
actual local merged-model path. Then explicitly run:

```bash
ollama create synthra-custom -f Modelfile
export SYNTHRA_MODEL=synthra-custom
```

Export does not merge weights or invoke `ollama create`. Keep the original base
model available until the adapter has been merged and evaluated.
