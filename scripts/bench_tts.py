#!/usr/bin/env python3
"""Benchmark d'un moteur TTS local : vitesse (caractères/min), RTF, mémoire.

Usage (depuis la racine du repo) :
    .venv/bin/python scripts/bench_tts.py --engine qwen3 --voice spk:Ryan
    .venv/bin/python scripts/bench_tts.py --engine qwen3 --voice ref:claire
    .venv/bin/python scripts/bench_tts.py --engine kyutai --voice unmute-prod-website/developpeuse-3.wav
"""

import argparse
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import engines  # noqa: E402
from app.audio import wav_duration, mp3_duration  # noqa: E402

BENCH_TEXT = (
    "Le vent d'automne balayait les feuilles mortes le long de l'avenue déserte. "
    "Claire remonta le col de son manteau et pressa le pas : la librairie fermait "
    "à dix-neuf heures, et il lui restait exactement douze minutes. Elle repensa "
    "à la lettre trouvée le matin même dans la boîte, à cette écriture penchée "
    "qu'elle aurait reconnue entre mille. « Rejoins-moi là où tout a commencé », "
    "disait simplement le message, sans signature. Était-ce une plaisanterie ? "
    "Un piège, peut-être ? Elle poussa la porte vitrée, et la clochette tinta "
    "dans le silence chaud de la boutique, entre les rayonnages de vieux livres."
) * 2  # ~1 100 caractères


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=["qwen3", "kyutai"])
    parser.add_argument("--voice", required=True)
    parser.add_argument("--language", default="fr")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    engine = engines.get_engine(args.engine)
    ok, reason = engine.availability()
    if not ok:
        sys.exit(f"Moteur indisponible : {reason}")

    out = Path(args.out) if args.out else Path(f"/tmp/bench_{args.engine}.{engine.chunk_ext}")

    print(f"Moteur {args.engine}, voix {args.voice}, {len(BENCH_TEXT)} caractères…")
    t0 = time.time()
    engines.activate(args.engine)
    load_time = time.time() - t0
    print(f"  chargement du modèle : {load_time:.1f}s")

    t1 = time.time()
    engine.synthesize(BENCH_TEXT, out, voice_id=args.voice, language=args.language)
    synth_time = time.time() - t1

    duration = wav_duration(out) if engine.chunk_ext == "wav" else mp3_duration(out)
    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    print(f"  synthèse : {synth_time:.1f}s pour {duration:.1f}s d'audio")
    print(f"  vitesse  : {len(BENCH_TEXT) / synth_time * 60:.0f} caractères/min")
    print(f"  RTF      : {synth_time / duration:.2f} (moins de 1.0 = plus vite que le temps réel)")
    print(f"  pic RAM (ce process) : {peak_gb:.1f} Go")
    print(f"  échantillon : {out}  (écouter : afplay {out})")
    engine.unload()


if __name__ == "__main__":
    main()
