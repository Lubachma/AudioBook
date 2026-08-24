#!/usr/bin/env python3
"""Worker TTS Kyutai (moshi-mlx) — tourne dans .venv-kyutai, isolé du venv principal.

Protocole ligne-à-ligne sur stdin/stdout :
  →  {"text": "…", "voice": "unmute-prod-website/developpeuse-3.wav", "out": "/chemin/sortie.wav"}
  ←  {"ok": true, "seconds": 12.3, "took": 4.5}   ou   {"ok": false, "error": "…"}

Une ligne {"ready": true} est émise une fois le modèle chargé. stdout est réservé
au protocole ; tous les logs vont sur stderr (redirigés vers data/logs/kyutai_worker.log).
Le worker s'arrête proprement quand stdin se ferme (mort du parent comprise).

Chargement calqué sur moshi_mlx/run_tts.py (implémentation canonique Kyutai).
"""

import argparse
import json
import sys
import time
import traceback


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def reply(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kyutai-worker")
    parser.add_argument("--hf-repo", default="kyutai/tts-1.6b-en_fr")
    parser.add_argument("--voice-repo", default="kyutai/tts-voices")
    parser.add_argument("--temp", type=float, default=0.6)
    parser.add_argument("--cfg-coef", type=float, default=2.0)
    parser.add_argument("--nq", type=int, default=32)
    parser.add_argument("--quantize", type=int, default=None,
                        help="Quantisation optionnelle du LM (ex. 8) pour accélérer.")
    args = parser.parse_args()

    log(f"[worker] chargement de {args.hf_repo} …")
    import mlx.core as mx
    import mlx.nn as nn
    import numpy as np
    import sentencepiece
    import sphn
    from moshi_mlx import models
    from moshi_mlx.models.tts import TTSModel
    from moshi_mlx.utils.loaders import hf_get

    mx.random.seed(299792458)

    with open(hf_get("config.json", args.hf_repo), "r") as fobj:
        raw_config = json.load(fobj)

    mimi_weights = hf_get(raw_config["mimi_name"], args.hf_repo)
    moshi_weights = hf_get(raw_config.get("moshi_name", "model.safetensors"), args.hf_repo)
    tokenizer_path = hf_get(raw_config["tokenizer_name"], args.hf_repo)

    lm_config = models.LmConfig.from_config_dict(raw_config)
    lm = models.Lm(lm_config)
    lm.set_dtype(mx.bfloat16)
    lm.load_pytorch_weights(str(moshi_weights), lm_config, strict=True)

    if args.quantize is not None:
        log(f"[worker] quantisation {args.quantize} bits")
        nn.quantize(lm.depformer, bits=args.quantize)
        for layer in lm.transformer.layers:
            nn.quantize(layer.self_attn, bits=args.quantize)
            nn.quantize(layer.gating, bits=args.quantize)

    text_tokenizer = sentencepiece.SentencePieceProcessor(str(tokenizer_path))  # type: ignore[call-arg]

    audio_tokenizer = models.mimi.Mimi(models.mimi_202407(lm_config.generated_codebooks))
    audio_tokenizer.load_pytorch_weights(str(mimi_weights), strict=True)

    tts_model = TTSModel(
        lm,
        audio_tokenizer,
        text_tokenizer,
        voice_repo=args.voice_repo,
        n_q=args.nq,
        temp=args.temp,
        cfg_coef=args.cfg_coef,
        max_padding=8,
        initial_padding=2,
        final_padding=4,
        padding_bonus=0.0,
        raw_config=raw_config,
    )

    cfg_coef_conditioning = None
    if tts_model.valid_cfg_conditionings:
        # Modèle entraîné avec distillation CFG : le coefficient passe en conditionnement.
        cfg_coef_conditioning = tts_model.cfg_coef
        tts_model.cfg_coef = 1.0
        cfg_is_no_text = False
        cfg_is_no_prefix = False
    else:
        cfg_is_no_text = True
        cfg_is_no_prefix = True
    mimi = tts_model.mimi

    log("[worker] modèle chargé, prêt.")
    reply({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            begin = time.time()
            mimi.reset_all()  # décodeur streaming à état : repartir propre à chaque chunk

            entries = tts_model.prepare_script([request["text"]], padding_between=1)
            if tts_model.multi_speaker:
                voices = [tts_model.get_voice_path(request["voice"])]
            else:
                voices = []
            attributes = tts_model.make_condition_attributes(voices, cfg_coef_conditioning)

            prefixes = None
            if not tts_model.multi_speaker:
                prefix_path = hf_get(request["voice"], args.voice_repo, check_local_file_exists=True)
                prefixes = [tts_model.get_prefix(prefix_path)]

            result = tts_model.generate(
                [entries],
                [attributes],
                prefixes=prefixes,
                cfg_is_no_prefix=cfg_is_no_prefix,
                cfg_is_no_text=cfg_is_no_text,
            )

            wav_frames = [mimi.decode_step(frame) for frame in result.frames]
            wavs = mx.concat(wav_frames, axis=-1)
            end_step = result.end_steps[0]
            if end_step is None:
                log("[worker] avertissement : end_step manquant, audio complet conservé")
                wav_length = wavs.shape[-1]
            else:
                wav_length = int(mimi.sample_rate * (end_step + tts_model.final_padding) / mimi.frame_rate)
            wav = wavs[0, :, :wav_length]
            if prefixes is not None:
                start = int(mimi.sample_rate * prefixes[0].shape[-1] / mimi.frame_rate)
                wav = wav[:, start:]

            sphn.write_wav(request["out"], np.array(mx.clip(wav, -1, 1)), mimi.sample_rate)
            reply({
                "ok": True,
                "seconds": round(wav.shape[-1] / mimi.sample_rate, 2),
                "took": round(time.time() - begin, 2),
            })
        except Exception as exc:  # noqa: BLE001 - le worker répond puis continue
            log(traceback.format_exc())
            reply({"ok": False, "error": str(exc)[:500]})

    log("[worker] stdin fermé, arrêt.")


if __name__ == "__main__":
    main()
