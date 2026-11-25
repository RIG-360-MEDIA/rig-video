"""Story graphics: one lower third per story (the first anchor part's) and 5+ ticker lines,
written only from each story's own facts."""

TICKER = {
 "efea": ["155 drones launched toward Moscow overnight", "Sobyanin: five reached the city and were shot down",
          "The rest intercepted at long range, the mayor says", "Air defence active across the Moscow region overnight",
          "Earlier incursions injured two people on Moscow's outskirts", "Moscow air defence stays on high alert after dawn"],
 "d616": ["Russia: 616 Ukrainian drones destroyed overnight", "Strikes reached 19 regions, the Moscow region and Crimea",
          "Over 80 drones downed over Rostov-on-Don, ministry says", "Sheremetyevo halts all arrivals and departures",
          "Four major airports close during the attack", "Drones also reported over the Azov and Black Seas"],
 "62ba": ["Drone attack hits Lipetsk in the early hours", "Governor Artamonov: one man, born in 2001, in hospital",
          "Debris hits polyclinic on Merkulov Street", "Windows shattered in several residential districts",
          "Repairs under way across the affected neighbourhoods"],
 "fr24": ["France: far-right groups attack marchers in three cities", "Nice, Montpellier and Nancy: masked men target protesters",
          "Police accused of standing by as attackers walk away", "Interior Minister Nuñez denies police complicity",
          "Legal complaints filed against far-right militias", "Opposition calls for an inquiry into the police response"],
}

LT_FIX = {"efea": {"headline": "MOSCOW REPELS OVERNIGHT DRONE WAVE", "subline": "155 drones launched toward the capital overnight"}}


def apply(p):
    k = p["id"].split("-")[1]
    first = next((s.get("lt") for s in p["versions"]["anchor_vo"] if s.get("lt")), None) or {"kicker": "", "headline": "", "subline": ""}
    for v in p["versions"].values():
        for s in v:
            s.pop("lt", None)
    p["lt"] = {**first, **LT_FIX.get(k, {})}
    p["ticker"] = TICKER[k]
    return p
