from datetime import time

from home_manager.config import Paths, load_config


def test_defaults_without_a_config_file(tmp_path):
    config = load_config(Paths(tmp_path))
    assert config.household_calendar == "Household"
    assert config.bill_list == "Bills" and config.bill_days == 3
    assert config.digest_to == () and config.digest_time == time(7, 0)


def test_full_config(tmp_path):
    (tmp_path / "config.toml").write_text('''
timezone = "America/Chicago"
[household]
calendar = "Family"
[calendars]
read = ["Family", "Home"]
[calendars.labels]
"Home" = "Nick"
[bills]
list = "Bills to pay"
remind_days = 5
[digest]
to = ["+15551234567"]
time = "06:45"
''')
    config = load_config(Paths(tmp_path))
    assert config.timezone.key == "America/Chicago"
    assert config.household_calendar == "Family"
    assert config.calendars == ("Family", "Home") and config.label("Home") == "Nick"
    assert (config.bill_list, config.bill_days) == ("Bills to pay", 5)
    assert config.digest_to == ("+15551234567",) and config.digest_time == time(6, 45)
