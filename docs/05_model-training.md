# Model Training Guide

**Version**: 2.0  
**Last Updated**: 2025-12-13

---

## Table of Contents

1. [Overview](#overview)
2. [Architectures](#architectures)
   - [Whisper Architecture](#whisper-architecture)
   - [E2E Architecture (Wav2Vec2 + mBART)](#e2e-architecture-wav2vec2--mbart)
3. [Training Pipeline](#training-pipeline)
4. [Data Pipeline](#data-pipeline)
5. [Configuration Deep Dive](#configuration-deep-dive)
6. [Model Loading & Tokenizers](#model-loading--tokenizers)
7. [Training Process](#training-process)
8. [Evaluation & Metrics](#evaluation--metrics)
9. [Output Artifacts](#output-artifacts)
10. [Running the Pipeline](#running-the-pipeline)

---

## 1. Overview

This training pipeline implements **Vietnamese-English Code-Switching Speech Translation** using two distinct architectures:

| Architecture | Components | Target Task |
|--------------|------------|-------------|
| **Whisper** | `openai/whisper-small` (244M) | **ASR only** (code-switch → transcript) |
| **E2E** | `wav2vec2-base` encoder + `mbart-large-50` decoder | ASR + **Vietnamese translation** |

### Performance Targets

| Model | Metric | Target | Description |
|-------|--------|--------|-------------|
| Whisper | **WER** | < 20% | Word Error Rate (ASR) |
| Whisper | **CER** | < 15% | Character Error Rate (ASR) |
| E2E | **WER** | < 25% | Word Error Rate (ASR) |
| E2E | **BLEU** | > 20 | Translation quality (Vietnamese) |
| E2E | **CHRF** | > 40 | Character-level translation |

---

## 2. Architectures

### Whisper Architecture

**Model**: OpenAI Whisper (encoder-decoder transformer)

| Variant | Parameters | HuggingFace Model ID | Use Case |
|---------|------------|----------------------|----------|
| Tiny | 39M | `openai/whisper-tiny` | Development (4GB VRAM) |
| Base | 74M | `openai/whisper-base` | Development |
| Small | 244M | `openai/whisper-small` | Production (light) |
| Medium | 769M | `openai/whisper-medium` | Production (recommended) |
| Large-v3 | 1.55B | `openai/whisper-large-v3` | Maximum quality |

#### Processor & Tokenizer

```python
from transformers import WhisperProcessor, WhisperForConditionalGeneration

# Processor contains both feature extractor and tokenizer
processor = WhisperProcessor.from_pretrained("openai/whisper-tiny")

# Feature Extractor: WhisperFeatureExtractor
#   - Converts raw audio → log-mel spectrogram
#   - Sample rate: 16kHz
#   - n_mels: 80
#   - n_fft: 400
#   - hop_length: 160

# Tokenizer: WhisperTokenizer (byte-level BPE)
#   - Vocabulary size: 50,364
#   - Language tokens: <|vi|>, <|en|>, etc.
#   - Task tokens: <|transcribe|>, <|translate|>
```

#### Whisper Task Configuration

```python
# Get decoder prompt IDs for Vietnamese ASR
forced_decoder_ids = processor.get_decoder_prompt_ids(
    language="vi",      # Source language
    task="transcribe"   # "transcribe" = ASR, "translate" = ST to English
)

# Output: [(1, <|vi|>), (2, <|transcribe|>)]
```

#### Multitask Training

When `task: "both"` is set, the `WhisperCollator` duplicates each batch:
- First half: `(audio, transcript)` → ASR task
- Second half: `(audio, translation)` → ST task

Effective batch size is **2x** nominal batch size.

---

### E2E Architecture (Wav2Vec2 + mBART)

**Architecture**: Speech Encoder-Decoder Model (custom)

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Raw Audio     │ → │   Wav2Vec2      │ → │   Adapter Layer │
│   (16kHz WAV)   │    │   Encoder       │    │   (Linear)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                      ↓
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Output       │ ← │   mBART-50      │ ← │   Encoder       │
│  (Text/Code)    │    │   Decoder       │    │   Hidden States │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

#### Encoder: Wav2Vec2

| Variant | Parameters | HuggingFace Model ID | Use Case |
|---------|------------|----------------------|----------|
| Base | 94M | `facebook/wav2vec2-base` | Development |
| Large-XLSR-53 | 317M | `facebook/wav2vec2-large-xlsr-53` | Production |

```python
from transformers import Wav2Vec2FeatureExtractor

# NOTE: Use FeatureExtractor, NOT Processor (wav2vec2-base has no tokenizer)
processor = Wav2Vec2FeatureExtractor.from_pretrained("facebook/wav2vec2-base")

# Feature Extractor: Wav2Vec2FeatureExtractor
#   - Converts raw audio → normalized waveform
#   - Sample rate: 16kHz
#   - Normalization: per-sample mean/std
#   - Return: input_values (raw waveform)

# Note: Wav2Vec2 does NOT use a tokenizer for input
# It learns representations directly from raw audio
```

#### Decoder: mBART-50

```python
from transformers import MBart50Tokenizer

tokenizer = MBart50Tokenizer.from_pretrained("facebook/mbart-large-50")

# Tokenizer: MBart50Tokenizer (SentencePiece)
#   - Vocabulary size: 250,054
#   - Supports 50 languages
#   - Language codes: vi_VN, en_XX, etc.
#   - Special tokens: <s>, </s>, <pad>, <unk>

# Decoder start token for Vietnamese output
decoder_start_token_id = tokenizer.lang_code_to_id["vi_VN"]  # = 250025
```

#### Special Task Tokens (E2E)

Custom tokens added to vocabulary for multitask:

```python
TRANSCRIBE_TOKEN = "<2transcribe>"  # ASR task marker
TRANSLATE_TOKEN = "<2translate>"    # ST task marker

# Added to tokenizer
tokenizer.add_special_tokens({
    'additional_special_tokens': [TRANSCRIBE_TOKEN, TRANSLATE_TOKEN]
})

# Example labels:
# ASR: "<2transcribe> Xin chào, how are you?"
# ST:  "<2translate> Xin chào, bạn khỏe không?"
```

#### Adapter Layer

When encoder hidden size ≠ decoder hidden size, a linear projection is added:

```python
# Wav2Vec2-Base: hidden_size = 768
# mBART-Large: d_model = 1024

# Adapter: Linear(768 → 1024)
model.enc_to_dec_proj = nn.Linear(encoder_dim, decoder_dim)
```

---

## 3. Training Pipeline

### 6-Step Pipeline Overview

```
[1/6] Install dependencies (PyTorch + CUDA)
[2/6] Prepare data
      [2a] Preprocess manifest (clean text, filter durations)
      [2b] Split data (train/val/test by video)
[3/6] Train Whisper
[4/6] Train E2E
[5/6] Evaluate on test set
[6/6] Generate charts
```

### Directory Structure

```
training/
├── configs/                    # YAML configurations
│   ├── base.yaml              # Shared defaults
│   ├── dev_whisper.yaml       # RTX 2050 Whisper
│   ├── dev_e2e.yaml           # RTX 2050 E2E
│   ├── prod_whisper.yaml      # H100 Whisper
│   └── prod_e2e.yaml          # H100 E2E
├── data/                       # Dataset utilities
│   ├── __init__.py
│   ├── dataset.py             # VietEngDataset class
│   ├── collator.py            # WhisperCollator, E2ECollator
│   ├── split_data.py          # Train/val/test splitter
│   └── preprocess_manifest.py # NEW: Manifest cleaning
├── models/                     # Model wrappers
│   ├── __init__.py
│   ├── whisper_wrapper.py     # WhisperWrapper class
│   └── e2e_model.py           # E2EModel + SpeechEncoderDecoderModelWrapper
├── scripts/                    # Training scripts
│   ├── __init__.py
│   ├── train.py               # Unified training script
│   ├── run_evaluation.py      # Evaluation script
│   └── export_charts.py       # Visualization generator
├── utils/                      # Utilities
│   ├── __init__.py
│   ├── callbacks.py           # Custom Trainer callbacks
│   ├── logger.py              # Training logger
│   └── metrics.py             # WER, BLEU, CHRF + normalize_for_eval
├── requirements.txt           # Training dependencies
├── run_dev.bat                # Windows development script
└── run_prod.sh                # Linux production script
```

---

## 4. Data Pipeline

### 4.1 Data Preprocessing (NEW)

**Source**: `training/data/preprocess_manifest.py`

Before training, the raw manifest must be cleaned:

```bash
# Clean manifest (removes markdown, empty rows, filters by duration)
python training/data/preprocess_manifest.py \
    --input data/export/manifest.tsv \
    --output data/export/manifest_clean.tsv
```

**Cleaning Steps**:

| Step | Action | Example |
|------|--------|---------|
| Strip markdown | Remove `[laughter]`, `[music]`, `[cười]` | `[cười] Xin chào` → `Xin chào` |
| Strip emphasis | Remove `**bold**`, `*italics*` | `**Hello**` → `Hello` |
| Normalize whitespace | Collapse multiple spaces, strip NBSP | `Hello  world` → `Hello world` |
| Filter empty | Remove rows with empty transcript/translation | - |
| Filter too short | Remove audio < 0.5s | - |
| Cap too long | Truncate duration > 30s to 30s | - |

### 4.2 Dataset: VietEngDataset

**Source**: `training/data/dataset.py`

```python
class VietEngDataset(Dataset):
    """
    Loads audio + transcripts from CSV splits.
    
    Expected CSV columns:
      - audio_path: relative path to WAV file
      - transcript: original code-switched text
      - translation: Vietnamese translation
      - duration: audio length in seconds
    """
    
    def __init__(
        self,
        csv_path: Path,
        audio_root: Path = ".",
        sample_rate: int = 16000,
        max_audio_length: float = 30.0
    ):
        pass
    
    def __getitem__(self, idx: int) -> Dict:
        return {
            'audio': torch.Tensor,       # Raw waveform (1D)
            'sample_rate': 16000,
            'transcript': str,           # Code-switched text
            'translation': str,          # Vietnamese translation
            'audio_path': str,           # For debugging
            'duration': float            # Seconds
        }
```

### Audio Preprocessing

```python
# Load audio with torchaudio
waveform, sr = torchaudio.load(audio_path)

# Convert stereo to mono
if waveform.shape[0] > 1:
    waveform = waveform.mean(dim=0, keepdim=True)

# Resample to 16kHz if needed
if sr != 16000:
    resampler = torchaudio.transforms.Resample(sr, 16000)
    waveform = resampler(waveform)

# Flatten to 1D
waveform = waveform.squeeze(0)

# Truncate to max length (30s = 480,000 samples)
max_samples = int(30.0 * 16000)
if waveform.shape[0] > max_samples:
    waveform = waveform[:max_samples]
```

### Data Collators

#### WhisperCollator

**Source**: `training/data/collator.py`

```python
@dataclass
class WhisperCollator:
    """
    Converts batch of samples to Whisper input format.
    
    Input: List[Dict] with 'audio', 'transcript', 'translation'
    Output: {
        'input_features': torch.Tensor [B, 80, 3000],  # Log-mel spectrogram
        'labels': torch.Tensor [B, seq_len]            # Tokenized text
    }
    """
    processor: WhisperProcessor
    task: str = "both"  # "transcribe", "translate", or "both"
    language: str = "vi"
    max_length: int = 448  # Max label tokens
    
    def __call__(self, features: List[Dict]) -> Dict:
        # Process audio → log-mel spectrogram
        audio_samples = [f['audio'].numpy() for f in features]
        batch = self.processor(
            audio_samples,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True
        )
        
        # Tokenize labels
        # For multitask: duplicate batch, first half = transcripts, second half = translations
        ...
```

#### E2ECollator

```python
@dataclass
class E2ECollator:
    """
    Converts batch of samples to Wav2Vec2+mBART input format.
    
    Input: List[Dict] with 'audio', 'transcript', 'translation'
    Output: {
        'input_values': torch.Tensor [B, seq_len],     # Raw waveform
        'attention_mask': torch.Tensor [B, seq_len],   # Padding mask
        'labels': torch.Tensor [B, label_len]          # Tokenized text with task token
    }
    """
    audio_processor: Wav2Vec2Processor
    tokenizer: MBart50Tokenizer
    task: str = "both"
    max_input_length: int = 480000  # 30s at 16kHz
    max_label_length: int = 256
    
    TRANSCRIBE_TOKEN = "<2transcribe>"
    TRANSLATE_TOKEN = "<2translate>"
    
    def __call__(self, features: List[Dict]) -> Dict:
        # Process audio → raw waveform
        audio_samples = [f['audio'].numpy() for f in features]
        processed = self.audio_processor(
            audio_samples,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
            max_length=self.max_input_length,
            truncation=True
        )
        
        # Tokenize labels with task prefix
        # Example: "<2transcribe> Xin chào everyone"
        ...
```

---

## 5. Configuration Deep Dive

### Base Configuration (`base.yaml`)

```yaml
# Shared defaults for all training runs

paths:
  data_root: "."
  manifest_path: "data/export/manifest.tsv"
  splits_dir: "data/splits"
  output_dir: "training/outputs"

audio:
  sample_rate: 16000
  max_length_seconds: 30

training:
  seed: 42
  eval_strategy: "steps"
  logging_steps: 50
  save_total_limit: 3
  load_best_model_at_end: true
  metric_for_best_model: "eval_loss"
  greater_is_better: false
  report_to: "tensorboard"

dataloader:
  num_workers: 4
  pin_memory: true
  prefetch_factor: 2
```

### Development Config: Whisper (`dev_whisper.yaml`)

```yaml
# RTX 2050 4GB - Minimal config

model:
  name: "openai/whisper-tiny"
  type: "whisper"
  language: "vi"
  task: "both"  # Multitask: ASR + ST

training:
  batch_size: 1
  gradient_accumulation_steps: 4
  # Effective batch size: 1 * 4 * 2 (multitask) = 8
  
  learning_rate: 1.0e-4
  lr_scheduler_type: "linear"
  warmup_ratio: 0.1         # 10% of steps for warmup
  weight_decay: 0.01
  max_grad_norm: 1.0        # Gradient clipping
  
  num_train_epochs: 2
  max_steps: 100            # Quick test run
  
  fp16: true                # Mixed precision
  gradient_checkpointing: false  # DISABLED: causes issues with multitask batch doubling
  
  eval_steps: 25
  save_steps: 50
  logging_steps: 10

output:
  dir: "training/outputs/dev_whisper"
  experiment_name: "whisper_tiny_dev"
```

### Development Config: E2E (`dev_e2e.yaml`)

```yaml
# RTX 2050 4GB - E2E with frozen encoder

model:
  type: "e2e"
  encoder: "facebook/wav2vec2-base"     # 94M params
  decoder: "facebook/mbart-large-50"    # 611M params
  add_adapter: true                      # Bridge layer
  freeze_encoder: true                   # Critical for 4GB VRAM

training:
  batch_size: 1
  gradient_accumulation_steps: 8
  # Effective batch size: 1 * 8 * 2 (multitask) = 16
  
  learning_rate: 1.0e-5    # Lower LR for large model
  lr_scheduler_type: "cosine"
  warmup_ratio: 0.15
  
  fp16: true
  gradient_checkpointing: false  # DISABLED: causes backward graph issues with batch doubling
  
  freeze_feature_encoder: true   # Freeze CNN layers
  freeze_encoder_epochs: 999     # Never unfreeze during dev

output:
  dir: "training/outputs/dev_e2e"
  experiment_name: "e2e_base_dev"
```

### Config Inheritance

Configs can inherit from base using `_base_`:

```yaml
_base_: "base.yaml"

model:
  name: "openai/whisper-medium"
  # ... overrides
```

---

## 6. Model Loading & Tokenizers

### Whisper Loading

**Source**: `training/models/whisper_wrapper.py`

```python
class WhisperWrapper:
    def __init__(
        self,
        model_name: str = "openai/whisper-small",
        language: str = "vi",
        task: str = "transcribe"
    ):
        # Load processor (feature extractor + tokenizer)
        self.processor = WhisperProcessor.from_pretrained(model_name)
        
        # Load model
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name)
        
        # Configure for Vietnamese
        self.model.config.forced_decoder_ids = self.processor.get_decoder_prompt_ids(
            language=language,
            task=task
        )
        self.model.config.suppress_tokens = []  # Allow all tokens
        
    def prepare_for_training(
        self,
        gradient_checkpointing: bool = False,
        freeze_encoder: bool = False
    ):
        if gradient_checkpointing:
            self.model.gradient_checkpointing_enable()
        
        if freeze_encoder:
            for param in self.model.model.encoder.parameters():
                param.requires_grad = False
```

### E2E Loading

**Source**: `training/models/e2e_model.py`

```python
class E2EModel:
    def __init__(
        self,
        encoder_name: str = "facebook/wav2vec2-large-xlsr-53",
        decoder_name: str = "facebook/mbart-large-50",
        add_adapter: bool = True
    ):
        # Load Wav2Vec2 processor (feature extractor only)
        self.audio_processor = Wav2Vec2Processor.from_pretrained(encoder_name)
        
        # Load mBART tokenizer
        self.tokenizer = MBart50Tokenizer.from_pretrained(decoder_name)
        
        # Add special task tokens
        special_tokens = {
            'additional_special_tokens': ["<2transcribe>", "<2translate>"]
        }
        self.tokenizer.add_special_tokens(special_tokens)
        
        # Build encoder-decoder model
        self.model = SpeechEncoderDecoderModel.from_encoder_decoder_pretrained(
            encoder_name,
            decoder_name
        )
        
        # Resize embeddings for new tokens
        self.model.decoder.resize_token_embeddings(len(self.tokenizer))
        
        # Configure decoder
        self.model.config.decoder_start_token_id = self.tokenizer.lang_code_to_id["vi_VN"]
        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.model.config.eos_token_id = self.tokenizer.eos_token_id
        
        # Add adapter layer if dimensions mismatch
        if add_adapter:
            encoder_dim = self.model.encoder.config.hidden_size  # 768 or 1024
            decoder_dim = self.model.decoder.config.d_model       # 1024
            if encoder_dim != decoder_dim:
                self.model.enc_to_dec_proj = nn.Linear(encoder_dim, decoder_dim)
    
    def prepare_for_training(
        self,
        gradient_checkpointing: bool = False,
        freeze_encoder: bool = False,
        freeze_feature_encoder: bool = True
    ):
        if gradient_checkpointing:
            self.model.gradient_checkpointing_enable()
        
        if freeze_encoder:
            for param in self.model.encoder.parameters():
                param.requires_grad = False
        elif freeze_feature_encoder:
            # Freeze only CNN feature extractor (7 conv layers)
            self.model.encoder.freeze_feature_encoder()
```

---

## 7. Training Process

### Training Script (`train.py`)

**Source**: `training/scripts/train.py`

```python
def train_whisper(config: Dict, resume_from: Optional[str] = None):
    # 1. Load model
    model = WhisperWrapper(
        model_name=config['model']['name'],
        language=config['model']['language'],
        task='transcribe'
    )
    model.prepare_for_training(
        gradient_checkpointing=config['training']['gradient_checkpointing'],
        freeze_encoder=config['training'].get('freeze_encoder', False)
    )
    
    # 2. Setup datasets
    train_dataset = VietEngDataset(csv_path='data/splits/train.csv')
    eval_dataset = VietEngDataset(csv_path='data/splits/dev.csv')
    collator = WhisperCollator(processor=model.get_processor(), task="both")
    
    # 3. Create training arguments
    training_args = Seq2SeqTrainingArguments(
        output_dir=config['output']['dir'],
        per_device_train_batch_size=config['training']['batch_size'],
        gradient_accumulation_steps=config['training']['gradient_accumulation_steps'],
        learning_rate=config['training']['learning_rate'],
        fp16=config['training']['fp16'],
        gradient_checkpointing=config['training']['gradient_checkpointing'],
        eval_strategy="steps",
        predict_with_generate=True,
        generation_max_length=256,
        ...
    )
    
    # 4. Create compute_metrics function
    compute_metrics = create_compute_metrics_fn(
        tokenizer=model.get_processor().tokenizer,
        metric_type='asr'  # WER, CER
    )
    
    # 5. Create trainer
    trainer = Seq2SeqTrainer(
        model=model.get_model(),
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
        tokenizer=model.get_processor().feature_extractor,
        compute_metrics=compute_metrics,
        callbacks=[
            LoggingCallback(logger),
            MetricsSaveCallback(output_dir, experiment_name),
            ConvergenceMonitorCallback()
        ]
    )
    
    # 6. Train
    trainer.train(resume_from_checkpoint=resume_from)
    
    # 7. Save
    trainer.save_model()
    model.get_processor().save_pretrained(output_dir)
```

### Custom Callbacks

**Source**: `training/utils/callbacks.py`

| Callback | Purpose |
|----------|---------|
| `LoggingCallback` | Logs loss, LR, eval metrics during training |
| `EncoderUnfreezeCallback` | Unfreezes encoder after N epochs (E2E only) |
| `MetricsSaveCallback` | Saves metrics history to JSON after training |
| `ConvergenceMonitorCallback` | Warns if loss not improving after 500 steps |

---

## 8. Evaluation & Metrics

### Metrics Computed

**Source**: `training/utils/metrics.py`

| Metric | Formula | Library | Use |
|--------|---------|---------|-----|
| **WER** | Word Error Rate | `jiwer` | ASR quality |
| **CER** | Character Error Rate | `jiwer` | ASR quality |
| **BLEU** | SacreBLEU | `sacrebleu` via `evaluate` | Translation quality |
| **CHRF** | Character n-gram F-score | `chrf` via `evaluate` | Translation quality |

```python
class MetricsComputer:
    def __init__(self):
        self.bleu_metric = evaluate.load("sacrebleu")
        self.chrf_metric = evaluate.load("chrf")
    
    def compute_wer(self, predictions: List[str], references: List[str]) -> float:
        return wer(references, predictions) * 100  # Returns 0-100
    
    def compute_bleu(self, predictions: List[str], references: List[str]) -> float:
        refs_formatted = [[r] for r in references]  # sacrebleu format
        return self.bleu_metric.compute(predictions=predictions, references=refs_formatted)['score']
```

### Evaluation Script (`run_evaluation.py`)

```bash
python training/scripts/run_evaluation.py \
    --model_dir training/outputs/dev_whisper \
    --model_type whisper \
    --test_csv data/splits/test.csv \
    --output training/outputs/results
```

**Output Files**:
- `{model_name}_metrics.json`: WER, CER, BLEU, CHRF, latency
- `{model_name}_predictions.csv`: All predictions vs references

---

## 9. Output Artifacts

After training completes:

```
training/outputs/
├── dev_whisper/                    # Whisper checkpoints
│   ├── config.json                 # Model config
│   ├── generation_config.json      # Generation settings
│   ├── model.safetensors          # Model weights
│   ├── preprocessor_config.json   # Feature extractor config
│   ├── tokenizer.json             # Tokenizer vocab
│   ├── vocab.json                 # Vocabulary
│   ├── train_results.json         # Training metrics
│   ├── logs/                      # TensorBoard logs
│   └── metrics/                   # Per-eval metrics history
│       └── whisper_tiny_dev_metrics.json
├── dev_e2e/                        # E2E checkpoints
│   ├── config.json
│   ├── model.safetensors
│   ├── preprocessor_config.json   # Wav2Vec2 processor
│   ├── tokenizer_config.json      # mBART tokenizer
│   ├── sentencepiece.bpe.model    # SentencePiece model
│   └── ...
├── results/                        # Evaluation results
│   ├── dev_whisper_metrics.json
│   ├── dev_whisper_predictions.csv
│   ├── dev_e2e_metrics.json
│   └── dev_e2e_predictions.csv
└── charts/                         # Visualizations
    ├── training_loss.png
    ├── wer_comparison.png
    └── bleu_comparison.png
```

---

## 10. Running the Pipeline

### Development (Windows, RTX 2050)

```powershell
# From project root
training\run_dev.bat
```

This script will:
1. Create virtual environment in `training/.venv/`
2. Install PyTorch with CUDA 12.4
3. Install training dependencies from `training/requirements.txt`
4. Split data into train/val/test (80/10/10)
5. Train Whisper-tiny (~10 min)
6. Train E2E (~20 min)
7. Evaluate both models
8. Generate charts

### Production (Linux H100)

```bash
# From project root
./training/run_prod.sh
```

**Production Settings:**
- **Whisper-small** (244M): **ASR only**, 4 epochs
- **wav2vec2-base + mbart-large-50**: ASR + Vietnamese translation, 4 epochs
- Encoder **frozen** to save VRAM
- **Batched evaluation** (16 samples/batch Whisper, 8 samples/batch E2E)

**Metrics per Model:**
| Model | Metrics |
|-------|---------|
| Whisper | WER, CER |
| E2E | WER, CER, BLEU, CHRF |

### Manual Training (One-liner)

```bash
source training/.venv/bin/activate && python training/scripts/train.py --config training/configs/prod_whisper.yaml && python training/scripts/train.py --config training/configs/prod_e2e.yaml && python training/scripts/run_evaluation.py --model_dir training/outputs/prod_whisper --model_type whisper --output training/outputs/results && python training/scripts/run_evaluation.py --model_dir training/outputs/prod_e2e --model_type e2e --output training/outputs/results
```

### Manual Training (Step by Step)

```bash
# Activate venv
source training/.venv/bin/activate  # Linux
training\.venv\Scripts\activate     # Windows

# Train Whisper (ASR only)
python training/scripts/train.py --config training/configs/prod_whisper.yaml

# Train E2E (ASR + Vietnamese translation)
python training/scripts/train.py --config training/configs/prod_e2e.yaml

# Evaluate Whisper (WER, CER)
python training/scripts/run_evaluation.py --model_dir training/outputs/prod_whisper --model_type whisper --output training/outputs/results

# Evaluate E2E (WER, CER, BLEU, CHRF)
python training/scripts/run_evaluation.py --model_dir training/outputs/prod_e2e --model_type e2e --output training/outputs/results
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| CUDA out of memory | Reduce `batch_size` to 1-2, set `freeze_encoder: true`, use `wav2vec2-base` instead of `xlsr-53` |
| `RuntimeError: backward through graph twice` | **DISABLE** `gradient_checkpointing` (multitask batch doubling is incompatible) |
| `TypeError: expected str, bytes...NoneType` (E2E) | Use `Wav2Vec2FeatureExtractor` instead of `Wav2Vec2Processor` (xlsr-53 has no tokenizer) |
| `TypeError: num_items_in_batch` (E2E) | Fixed: `SpeechEncoderDecoderModelWrapper` filters unsupported args |
| `IndexError: piece id out of range` (E2E eval) | Fixed: Token IDs clipped in `metrics.py` before decoding |
| `TypeError: shared tensors` (E2E saving) | Fixed: `save_safetensors=False` in training args |
| `KeyError: 'audio'` | Fixed: `remove_unused_columns=False` in training args |
| Slow evaluation | Use **batched inference** (16 samples/batch for Whisper, 8 for E2E) |
| Slow training | Increase `num_workers`, enable `tf32: true` on H100 |
| Import errors | Delete `training/.venv/` and re-run setup script |
| WER not improving | Check learning rate (try 1e-5), verify data quality |
| High WER/BLEU despite correct output | Fixed: Evaluation normalization strips punctuation/case |

---

## Dependencies

**training/requirements.txt** (PyTorch installed separately with CUDA):

```
# Core Deep Learning
transformers>=4.36.0
datasets>=2.14.0
accelerate>=0.24.0

# Audio Processing
librosa>=0.10.0
soundfile>=0.12.0

# Metrics
jiwer>=3.0.0
sacrebleu>=2.3.0
evaluate>=0.4.0

# Visualization
matplotlib>=3.7.0
seaborn>=0.12.0
pandas>=2.0.0

# Logging
tensorboard>=2.14.0

# Configuration
pyyaml>=6.0
omegaconf>=2.3.0

# Utilities
tqdm>=4.65.0
numpy>=1.24.0
```
