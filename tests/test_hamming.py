from sold_item_finder.core.similarity import hamming_distance


def test_hamming_distance():
    assert hamming_distance("abcd", "abcf") == 1
