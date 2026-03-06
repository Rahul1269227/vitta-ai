from sentinelfi.services.taxonomy_service import TaxonomyService


def test_taxonomy_service_loads_sample_taxonomy() -> None:
    service = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )
    assert service.has_category("food_dining")
    assert service.has_category("subscriptions_memberships")


def test_taxonomy_service_matches_category_and_overrides() -> None:
    service = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )
    matched = service.match_category("monthly slack workspace invoice")
    assert matched is not None

    category_id, score, keywords = matched
    assert category_id in {"subscriptions_memberships", "bills", "professional_services"}
    assert score > 0
    assert isinstance(keywords, list)


def test_taxonomy_service_maps_mcc_overrides() -> None:
    service = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )
    assert service.category_for_mcc("5734") == "electronics_technology"


def test_taxonomy_service_loads_signal_groups() -> None:
    service = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )
    simple = service.signal_keywords("simple_merchants")
    assert "swiggy" in simple
    assert "zoom" in simple
