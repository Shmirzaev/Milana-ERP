from app.core.model_search import model_code_contains, normalized_model_code_key


def test_model_code_normalization_folds_latin_and_cyrillic_lookalikes():
    assert normalized_model_code_key("PJ-1000") == normalized_model_code_key("РJ-1000")
    assert normalized_model_code_key("СУПРЕМ") == "cyпpem"


def test_model_code_contains_matches_variant_codes_across_alphabets():
    assert model_code_contains("РJ-1000-194", "PJ-1000")
    assert model_code_contains("PJ-1000/4", "РJ-1000")
    assert not model_code_contains("TJ-1000", "PJ-1000")
