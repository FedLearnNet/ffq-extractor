from pathlib import Path

from ffq_extractor.mapping import default_mapping_path, load_food_mapping

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data" / "Matching_nutritional_variables.xlsx"


def test_default_mapping_path_resolves():
    path = default_mapping_path()
    assert path.is_file()


def test_load_mapping_strips_spaces_and_skips_sections():
    mapping = load_food_mapping(MAPPING)
    assert len(mapping) == 146
    assert "Meat, fish, poultry - Medium serving (size deck of cards)" not in mapping

    beef = mapping["Beef (roast / steak)"]
    assert beef.food_group == "Meat/fish/eggs and substitutes"
    assert beef.food_subgroup == "Meat excluding offal"

    stew = mapping["Beef: stew"]
    assert stew.food_group == "Ready meals and sandwiches"
    assert stew.food_subgroup == "Ready meals"
    assert not stew.food_group.endswith(" ")
    assert not stew.food_subgroup.endswith(" ")


def test_na_mapped_items():
    mapping = load_food_mapping(MAPPING)
    pickles = mapping["Pickles, chutney (tablespoon)"]
    assert pickles.is_na
