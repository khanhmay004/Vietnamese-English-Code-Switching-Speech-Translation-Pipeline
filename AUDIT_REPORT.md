# COMPREHENSIVE PIPELINE AUDIT REPORT

**Date**: 2025-12-13  
**Auditor**: Antigravity AI  
**Scope**: Full training pipeline codebase

---

## EXECUTIVE SUMMARY

| Status | Count |
|--------|-------|
| 🔴 **Critical Issues Found** | 2 |
| 🟡 **Medium Issues Found** | 3 |
| 🟢 **Already Fixed** | 4 |

---

## 🔴 CRITICAL ISSUES

### Issue 1: E2E Model Generation Missing Forced BOS Token
**File**: `training/scripts/run_evaluation.py` (lines 194-201)  
**Status**: ✅ FIXED

**Problem**: E2E model generation did NOT set `forced_bos_token_id`, causing decoder to start with wrong language token. Output was garbage text.

**Fix Applied**:
```python
forced_bos_token_id = tokenizer.lang_code_to_id.get("vi_VN", None)
generated_ids = model.generate(
    input_values,
    forced_bos_token_id=forced_bos_token_id,
    no_repeat_ngram_size=3,  # Prevent degenerate repetition
    ...
)
```

---

### Issue 2: Metrics Not Normalized Before Scoring
**File**: `training/utils/metrics.py`  
**Status**: ✅ FIXED

**Problem**: `compute_wer`, `compute_cer`, `compute_bleu`, `compute_chrf` did NOT normalize text before scoring. Punctuation, case, and special tokens inflated error rates dramatically.

**Fix Applied**: All metric methods now call `normalize_for_eval()` on both predictions and references.

---

## 🟡 MEDIUM ISSUES

### Issue 3: Whisper Multitask Training Confusion
**File**: `training/configs/prod_whisper.yaml`  
**Status**: ✅ FIXED (changed to ASR-only)

**Problem**: Whisper's `translate` task outputs English, but training labels were Vietnamese. Model was trained with mismatched targets.

**Root Cause**: Misunderstanding of Whisper's translate behavior.

**Fix**: Changed to `task: "transcribe"` (ASR only).

---

### Issue 4: No Sanity Check for Model Outputs
**File**: `training/scripts/run_evaluation.py`  
**Status**: ⚠️ NOT YET FIXED

**Problem**: No logging of sample predictions to catch garbage outputs early.

**Recommendation**: Add logging of first 3 predictions for manual inspection.

---

### Issue 5: No Tokenizer Vocabulary Validation
**File**: `training/models/e2e_model.py`  
**Status**: ⚠️ NOT YET FIXED

**Problem**: No validation that tokenizer can encode Vietnamese text correctly.

**Recommendation**: Add test during model initialization.

---

## 🟢 ALREADY CORRECT

| Component | Status | Notes |
|-----------|--------|-------|
| Dataset loading | ✅ | Handles mono conversion, resampling |
| WhisperCollator | ✅ | Properly handles single-task mode |
| E2ECollator | ✅ | Correct task token prefixing |
| E2E model saving | ✅ | Saves config.json correctly |
| Training args | ✅ | Uses tf32, bf16 properly |

---

## REMAINING IMPROVEMENTS TO IMPLEMENT

### 1. Add Sample Prediction Logging

```python
# In run_evaluation.py, after generating predictions:
if batch_start == 0:  # Log first batch
    for i in range(min(3, len(pred_texts))):
        logger.info(f"Sample {i}:")
        logger.info(f"  Pred: {pred_texts[i][:100]}...")
        logger.info(f"  Ref:  {batch_refs[i][:100]}...")
```

### 2. Add Tokenizer Validation

```python
# In e2e_model.py __init__:
test_text = "Xin chào, hello world"
encoded = self.tokenizer.encode(test_text)
decoded = self.tokenizer.decode(encoded.ids, skip_special_tokens=True)
if decoded.strip() != test_text.strip():
    logger.warning(f"Tokenizer roundtrip failed: '{test_text}' -> '{decoded}'")
```

### 3. Add Early Stopping on Garbage Metrics

```python
# In callbacks.py:
class GarbageDetectionCallback(TrainerCallback):
    def on_evaluate(self, args, state, control, metrics, **kwargs):
        if metrics.get('eval_wer', 0) > 100:
            logger.error("WER > 100%! Investigation needed.")
            # Optionally stop training
```

---

## VERIFICATION CHECKLIST

Before each training run:

- [ ] Verify `task` setting matches labels in data
- [ ] Whisper: `task: "transcribe"` if labels are code-switch text
- [ ] E2E: Confirm `translation` column contains Vietnamese
- [ ] Run quick test with 10 samples to check output quality:
  
```bash
python -c "
from training.scripts.run_evaluation import *
model, proc, tok = load_e2e_model('training/outputs/prod_e2e')
# Test single audio file
"
```

---

## SUMMARY OF FIXES APPLIED TODAY

| File | Change |
|------|--------|
| `training/utils/metrics.py` | Added `normalize_for_eval()` to all metric methods |
| `training/scripts/run_evaluation.py` | Added `forced_bos_token_id` for E2E generation |
| `training/scripts/run_evaluation.py` | Added `no_repeat_ngram_size=3` to prevent repetition |
| `training/configs/prod_whisper.yaml` | Changed to `task: "transcribe"` |

---

**END OF AUDIT REPORT**
