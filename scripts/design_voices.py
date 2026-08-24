#!/usr/bin/env python3
"""Fabrique des voix de narration françaises avec Qwen3-TTS VoiceDesign (one-shot).

Pourquoi : les speakers préréglés de Qwen3-TTS CustomVoice sont zh/en/ja/ko —
aucune voix française native. On décrit donc des narratrices/narrateurs français
en toutes lettres, VoiceDesign génère un échantillon de référence, et le moteur
`qwen3` clone ensuite cette voix (modèle Base) pour lire les livres.

Produit, pour chaque voix : data/voices/<nom>.wav + data/voices/<nom>.txt
(le transcript EXACT de l'échantillon, requis par le clonage).

Usage (depuis la racine du repo) :
    .venv/bin/python scripts/design_voices.py            # toutes les voix
    .venv/bin/python scripts/design_voices.py --only claire
    .venv/bin/python scripts/design_voices.py --list

Le modèle VoiceDesign (~4 Go) n'est nécessaire que pour ce script ; il peut être
purgé du cache Hugging Face ensuite (hf cache delete).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audio import write_wav_int16  # noqa: E402
from app.config import settings  # noqa: E402

# Texte de référence (~15 s de parole) : riche en prosodie, dialogue et nombres.
REF_TEXT = (
    "Le soir tombait doucement sur la vieille ville, et les lampadaires s'allumaient "
    "un à un le long du quai. « Tu es en retard », murmura-t-elle sans se retourner. "
    "Il sourit, posa les deux tasses fumantes sur la table, et commença à raconter "
    "son étrange journée."
)

VOICE_DESIGNS = {
    "claire": (
        "Voix féminine française d'une quarantaine d'années, chaleureuse et posée, "
        "narratrice de romans, débit calme et régulier, timbre légèrement grave et "
        "doux, diction parfaite, ton intime comme une lecture du soir."
    ),
    "marianne": (
        "Voix féminine française d'une trentaine d'années, claire et lumineuse, "
        "articulation précise, ton vivant et expressif sans être théâtral, "
        "parfaite pour tenir l'attention sur un long roman."
    ),
    "victor": (
        "Voix masculine française d'une cinquantaine d'années, grave, profonde et "
        "rassurante, narrateur classique de livres audio, débit lent et posé, "
        "légère chaleur dans le timbre."
    ),
    "louise": (
        "Voix féminine française mûre, élégante et expressive, avec du relief dans "
        "l'intonation, capable de faire vivre les dialogues, style comédienne de "
        "théâtre qui lit un roman."
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Ne générer que cette voix (nom du dictionnaire).")
    parser.add_argument("--list", action="store_true", help="Lister les voix disponibles.")
    parser.add_argument("--model", default=settings.qwen3_voice_design_model)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()

    if args.list:
        for name, instruct in VOICE_DESIGNS.items():
            print(f"{name:10s} {instruct[:80]}…")
        return

    targets = {args.only: VOICE_DESIGNS[args.only]} if args.only else VOICE_DESIGNS
    settings.voices_dir.mkdir(parents=True, exist_ok=True)

    print(f"Chargement de {args.model} …")
    import numpy as np
    from mlx_audio.tts.utils import load_model

    model = load_model(args.model)

    for name, instruct in targets.items():
        out_wav = settings.voices_dir / f"{name}.wav"
        print(f"→ {name} : génération de l'échantillon de référence…")
        begin = time.time()
        results = model.generate_voice_design(
            text=REF_TEXT,
            instruct=instruct,
            language="french",
            temperature=args.temperature,
        )
        parts = [np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in results]
        samples = np.concatenate(parts)
        write_wav_int16(out_wav, samples, 24_000)
        out_wav.with_suffix(".txt").write_text(REF_TEXT, encoding="utf-8")
        print(f"  {out_wav} ({samples.size / 24_000:.1f}s, généré en {time.time() - begin:.0f}s)")

    print(
        "\nTerminé. Écoutez les wav dans data/voices/ (open data/voices) : supprimez ceux qui "
        "déplaisent, relancez avec --only <nom> pour retenter une voix (résultat aléatoire), "
        "puis comparez-les dans le banc d'essai de l'UI."
    )


if __name__ == "__main__":
    main()
