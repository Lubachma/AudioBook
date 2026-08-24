from app.chapters import Chapter
from app.chunker import chunk_by_chapters, chunk_text, split_sentences


def test_respects_max_chars():
    text = " ".join(f"Phrase numéro {i} avec du texte." for i in range(50))
    chunks = chunk_text(text, max_chars=200)
    assert chunks
    assert all(len(c) <= 200 for c in chunks)


def test_splits_at_sentence_boundaries():
    text = "Première phrase. Deuxième phrase. Troisième phrase."
    chunks = chunk_text(text, max_chars=len("Première phrase. Deuxième phrase."))
    assert chunks == ["Première phrase. Deuxième phrase.", "Troisième phrase."]


def test_long_sentence_split_at_space():
    words = " ".join("mot" for _ in range(100))  # une seule "phrase" très longue
    chunks = chunk_text(words, max_chars=50)
    assert all(len(c) <= 50 for c in chunks)
    # aucun mot coupé : la reconstruction redonne le texte d'origine
    assert " ".join(chunks) == words


def test_very_long_word_hard_cut():
    chunks = chunk_text("x" * 120, max_chars=50)
    assert chunks == ["x" * 50, "x" * 50, "x" * 20]


def test_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_split_sentences_punctuation():
    assert split_sentences("Ça va ? Oui ! Super…") == ["Ça va ?", "Oui !", "Super…"]


# ------------------------------------------------------- découpage par chapitre

def test_chunk_by_chapters_never_crosses_boundaries():
    part1 = "Chapitre un. " + "Une phrase courte. " * 10
    part2 = "Chapitre deux. " + "Une autre phrase. " * 10
    text = part1.strip() + " " + part2.strip()
    chapters = [Chapter("Un", 0), Chapter("Deux", len(part1))]

    chunks = chunk_by_chapters(text, chapters, max_chars=60)

    assert all(idx in (0, 1) for _, idx in chunks)
    # Aucun chunk du chapitre 1 ne contient le début du chapitre 2 et inversement
    for chunk, idx in chunks:
        if idx == 0:
            assert "Chapitre deux" not in chunk
        else:
            assert "Chapitre un" not in chunk
    # Les deux chapitres sont bien couverts
    assert {idx for _, idx in chunks} == {0, 1}


def test_chunk_by_chapters_without_chapters_is_single_index():
    text = "Une phrase. Une autre phrase. Encore une."
    chunks = chunk_by_chapters(text, [], max_chars=20)
    assert chunks
    assert all(idx == 0 for _, idx in chunks)
    assert [c for c, _ in chunks] == chunk_text(text, 20)


def test_chunk_by_chapters_deterministic():
    text = "Chapitre un. Texte. " * 20
    chapters = [Chapter("Un", 0), Chapter("Deux", 100)]
    assert chunk_by_chapters(text, chapters, 50) == chunk_by_chapters(text, chapters, 50)
