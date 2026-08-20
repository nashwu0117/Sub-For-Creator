# ASR Accuracy Acceptance Report

- **S1 VAD**: PASS — 15s silence: VAD on -> 0 segments (expect 0); VAD off -> 3 segments (hallucination contrast); timing VAD on 13.1s / off 91.7s
- **S2 Determinism**: PASS — pro tier (beam 10, temperature 0) twice -> identical: True; segments: 2; total 2 runs 46.3s
- **S3 Denoise**: PASS — noise floor: -13.0 dB -> -28.3 dB (improvement 15.3 dB, expect >= 5); denoise step 2.09s; CLI --denoise pipeline ok (exit 0, 2 segments)
- **S4 Dictionary**: PASS — dictionary terms ['OurWay', 'Nash', 'WhisperX'] matched: with = ['Nash', 'WhisperX'], without = none; with: 4 segs, without: 3 segs
- **S5 LLM correction**: PASS — fake Ollama provider: 2/2 segments corrected; timing preserved = True; pipeline with LLM pass 26.2s vs plain run 25.9s (provider latency dominates; fake server ~instant)

**Overall: ALL PASS**
