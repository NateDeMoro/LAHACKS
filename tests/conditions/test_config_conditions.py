from backend.config import CONFIG


def test_conditions_config_defaults():
    c = CONFIG.conditions
    assert c.enabled is True  # drafted rules are on from the start; this is the kill switch
    assert c.allowed_vitals == ("hr", "resp_rate", "spo2", "temp_c")  # sbp is a triage reading and is not graded
    assert c.min_sources == 2
    assert 0 < c.match_threshold <= 1
    assert c.menu_path.name == "limit_menu.json"
    assert "logs" in c.store_path.parts  # gitignored: evidence holds condition names
