from app.chunker import chunk_text, split_sentences


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
