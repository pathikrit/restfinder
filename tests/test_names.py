from restfinder.names import display_name


def test_all_uppercase_names_get_readable_display_casing():
    assert display_name("OLD TOWN BAR") == "Old Town Bar"
    assert display_name("MCDONALD'S") == "McDonald's"
    assert display_name("McDONALD'S") == "McDonald's"
    assert display_name("D'AGOSTINO") == "D'Agostino"


def test_known_acronyms_are_preserved():
    assert display_name("KYU NYC") == "Kyu NYC"
    assert display_name("JG MELON") == "JG Melon"
    assert display_name("S&P") == "S&P"


def test_source_styling_and_whitespace_are_preserved():
    assert display_name("  abcV   East  ") == "abcV East"
    assert display_name("Café China") == "Café China"
