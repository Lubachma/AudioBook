"""Tests de la normalisation du texte avant synthèse."""

from app.textnorm import normalize, roman_to_int


def test_invisible_chars_and_nbsp_removed():
    assert normalize("bon­jour​ le monde") == "bonjour le monde"


def test_footnote_markers_stripped():
    assert normalize("la maison1, puis le jardin23. Fin") == "la maison, puis le jardin. Fin"


def test_footnote_not_stripped_from_real_numbers():
    # Chiffres légitimes : isolés, ou après majuscule/chiffre — intacts
    assert normalize("Il avait 3 chats.") == "Il avait 3 chats."
    assert normalize("l'Apollo 11 décolla.") == "l'Apollo 11 décolla."


def test_titles_expanded_before_capitalized_names():
    assert normalize("M. Dupont salua Mme Claire et le Dr Martin.") == (
        "Monsieur Dupont salua Madame Claire et le Docteur Martin."
    )


def test_title_abbreviation_kept_when_not_a_name():
    # « M. » en fin de phrase ou devant une minuscule n'est pas une civilité sûre
    assert normalize("le point M. est fixe") == "le point M. est fixe"


def test_roman_chapter_numbers_converted():
    assert normalize("Chapitre IV") == "Chapitre 4"
    assert normalize("CHAPITRE XII, l'aube") == "CHAPITRE 12, l'aube"
    assert normalize("Chapter IX") == "Chapter 9"


def test_roman_conversion_needs_chapter_keyword():
    assert normalize("Louis XIV régnait.") == "Louis XIV régnait."
    assert normalize("la partie civile") == "la partie civile"


def test_roman_to_int():
    assert roman_to_int("IV") == 4
    assert roman_to_int("XIX") == 19
    assert roman_to_int("MCMXII") == 1912
    assert roman_to_int("HELLO") is None
