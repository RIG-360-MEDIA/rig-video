"""Check: first_reported finds the day an event was first reported. python test_event_date.py"""
import datetime as dt, os, sys
os.environ.setdefault("RIGVIDEO_TEST", "1")
sys.path.insert(0, os.path.dirname(__file__))
import worker
D = lambda s: dt.date.fromisoformat("2026-11-" + s)
q = worker.event_query("US Shoots Down Iranian Drones Targeting Bahrain Amid Escalating Middle East Tensions")
news = [(D("17"), "Iran's Revolutionary Guard claims another attack on U.S. radar system in Bahrain"),
        (D("15"), "Iran claims drone attack on US military airbase in Bahrain"),
        (D("13"), "Bahrain: United States said it intercepted Iranian drone attacks"),
        (D("13"), "US says shot down two Iranian drones targeted at Bahrain"),
        (dt.date(2026, 6, 6), "US strikes Iranian sites after Iran launches drones in latest Gulf flare-up"),
        (D("10"), "Bahrain fishing fleet sees record catch")]
assert worker.first_reported([q], news, D("14")) == D("13")              # story made the 14th, event the 13th
assert worker.first_reported([q], news[:1] + news[2:3], D("14")) is None  # one report on a day is not enough
assert worker.first_reported([q], news, D("12")) is None                 # nothing before the window's end
S = lambda t, made="2026-11-13": worker.stated_date(t, dt.date.fromisoformat(made))
assert S("November 9, around 12:00") == D("09") and S("Around 5:45 AM on October 24, 2024.") == dt.date(2024, 10, 24)
assert S("Shortly before midnight on a Thursday.") == D("12") and S("9th of November") == D("09")
assert S("December 30") == dt.date(2025, 12, 30) and S("this week") is None             # no future dates, no day named
aliaga = [(D("09"), "Explosion at steel plant in western Turkey leaves 16 dead"), (D("09"), "Turkey steel factory blast kills 17"),
          (D("12"), "Death toll in steel plant blast rises to 19")]
qs = ["The Silence After the Blast", "TURKEY STEEL PLANT BLAST DEATH TOLL"]
assert worker.first_reported(qs, aliaga, D("10"), back=1) == D("09")                   # the stated day, confirmed
assert worker.first_reported(qs, aliaga, D("13")) is None                              # 3-day rule alone would miss it
print("ok")
