import pytest

from ffq_extractor.frequencies import (
    frequency_code_for_header,
    is_accepted_mark,
    is_blank_cell,
)


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Less than once a month", "<1/M"),
        ("Once a month", "1/M"),
        ("Once a week", "1/W"),
        ("Twice a week", "2/W"),
        ("5 times a week", "5/W"),
        ("Once a day", "1/D"),
        ("Twice a day", "2/D"),
        ("4 times a day", "4/D"),
        ("6 or more times a day", "6+/D"),
        ("Never", None),
        ("never", None),
    ],
)
def test_frequency_codes(header, expected):
    assert frequency_code_for_header(header) == expected


def test_unknown_frequency_header():
    with pytest.raises(ValueError):
        frequency_code_for_header("Every fortnight")


@pytest.mark.parametrize("mark", ["X", "x", "1", "✓", "✔", "Y", "yes"])
def test_accepted_marks(mark):
    assert is_accepted_mark(mark)


@pytest.mark.parametrize("mark", [None, "", "  ", "NA", "n/a", "2"])
def test_rejected_or_blank_marks(mark):
    if mark is None or str(mark).strip() == "":
        assert is_blank_cell(mark)
        assert not is_accepted_mark(mark)
    else:
        assert not is_accepted_mark(mark)
