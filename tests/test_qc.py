"""Tests du contrôle qualité (comparaison de mots, sans whisper réel)."""

from app.qc import _normalize, words_ratio

SOURCE = (
    "Le soir tombait sur la vieille ville, et les lampadaires s'allumaient un à un "
    "le long du quai. « Tu es en retard », murmura Claire sans se retourner."
)


def test_identical_text_scores_one():
    assert words_ratio(SOURCE, SOURCE) == 1.0


def test_transcription_noise_scores_high():
    transcript = (
        "le soir tombait sur la vieille ville et les lampadaires s'allumaient un à un "
        "le long du quai tu es en retard murmura claire sans se retourner"
    )
    assert words_ratio(SOURCE, transcript) > 0.95


def test_truncated_audio_scores_low():
    transcript = "Le soir tombait sur la vieille ville."
    assert words_ratio(SOURCE, transcript) < 0.5


def test_repetition_hallucination_scores_low():
    transcript = ("le soir tombait " * 15).strip()
    assert words_ratio(SOURCE, transcript) < 0.6


def test_digits_are_ignored_on_both_sides():
    # whisper écrit « 37 » là où le texte dit « trente-sept » : ni l'un ni l'autre ne compte
    assert words_ratio("Il a compté 37 marches", "il a compté trente-sept marches") > 0.6
    assert _normalize("Page 12 et 14") == ["page", "et"]


def test_empty_expected_is_trivially_ok():
    assert words_ratio("", "peu importe") == 1.0
