from sold_item_finder.core.query_normalizer import QueryNormalizer


def test_query_normalizer_strips_prefixes():
    q = QueryNormalizer()
    assert q.normalize("Sold: Vintage Denim Jacket") == "vintage denim jacket"
    assert q.normalize("eBay item sold Blue Hat") == "blue hat"
