# Berliner PLZ nach Bezirken und Ortsteilen
# Quelle: berlinstadtservice.de

BEZIRKE = [
    "Mitte", "Friedrichshain-Kreuzberg", "Pankow",
    "Charlottenburg-Wilmersdorf", "Spandau", "Steglitz-Zehlendorf",
    "Tempelhof-Schöneberg", "Neukölln", "Treptow-Köpenick",
    "Marzahn-Hellersdorf", "Lichtenberg", "Reinickendorf"
]

# S-Bahn Ring PLZ (innerhalb des Rings)
INNERHALB_RING = {
    "10115", "10117", "10119",  # Mitte
    "10178", "10179",
    "10243", "10245", "10247", "10249",  # Friedrichshain
    "10315", "10317",  # Rummelsburg/Lichtenberg (teilw.)
    "10365", "10367", "10369",  # Lichtenberg
    "10405", "10407", "10409",  # Prenzlauer Berg
    "10435", "10437", "10439",
    "10551", "10553", "10555", "10557", "10559",  # Moabit/Tiergarten
    "10585", "10587", "10589",  # Charlottenburg (teilw.)
    "10623", "10625", "10627", "10629",
    "10707", "10709", "10711",  # Wilmersdorf/Charlottenburg
    "10713", "10715", "10717", "10719",
    "10777", "10779", "10781", "10783", "10785",  # Schöneberg
    "10787", "10789",
    "10823", "10825", "10827", "10829",
    "10961", "10963", "10965", "10967", "10969",  # Kreuzberg
    "10997", "10999",
    "12043", "12045", "12047", "12049",  # Neukölln (nördl.)
    "12051", "12053", "12055", "12057", "12059",
    "13347", "13349", "13351", "13353",  # Wedding
    "13355", "13357", "13359",
}

# PLZ nach Bezirken (für Stadtteil-Filter)
BEZIRK_PLZ = {
    "Mitte": {
        "10115", "10117", "10119", "10178", "10179",  # Mitte
        "10551", "10553", "10555", "10557", "10559",  # Moabit/Tiergarten
        "10785", "10787",
        "13347", "13349", "13351", "13353",  # Wedding/Gesundbrunnen
        "13355", "13357", "13359", "13405", "13407", "13409",
    },
    "Friedrichshain-Kreuzberg": {
        "10243", "10247", "10249",  # Friedrichshain
        "10785", "10961", "10963", "10965", "10967",  # Kreuzberg
        "10969", "10997", "10999",
    },
    "Prenzlauer Berg / Pankow": {
        "10247", "10249", "10405", "10407", "10409",  # Prenzlauer Berg
        "10435", "10437", "10439",
        "13086", "13088",  # Weißensee
        "13125", "13127", "13129",  # Buch/Karow/Blankenburg
        "13156", "13158", "13159",  # Rosenthal/Blankenfelde
        "13187", "13189",  # Pankow
    },
    "Neukölln": {
        "10965", "10967", "12043", "12045", "12047",
        "12049", "12051", "12053", "12055", "12057",
        "12059", "12099", "12305", "12347", "12349",
        "12351", "12353", "12355", "12357", "12359", "12435",
    },
    "Tempelhof-Schöneberg": {
        "10777", "10779", "10781", "10783", "10785",
        "10787", "10789", "10823", "10825", "10827", "10829",
        "10965", "12099", "12101", "12103", "12105",
        "12107", "12109", "12157", "12159", "12161",
        "12163", "12277", "12279", "12305", "12307", "12309",
    },
    "Charlottenburg-Wilmersdorf": {
        "10585", "10587", "10589", "10623", "10625",
        "10627", "10629", "10707", "10709", "10711",
        "10713", "10715", "10717", "10719", "10777",
        "10779", "10789", "10825", "13353", "13627",
        "13629", "14050", "14052", "14053", "14055",
        "14057", "14059", "14193", "14195", "14197", "14199",
    },
    "Lichtenberg": {
        "10315", "10317", "10318", "10319",
        "10365", "10367", "10369",
        "13051", "13053", "13055", "13057", "13059",
    },
    "Marzahn-Hellersdorf": {
        "12619", "12621", "12623", "12627", "12629",
        "12679", "12681", "12683", "12685", "12687", "12689",
    },
    "Reinickendorf": {
        "13403", "13405", "13407", "13409",
        "13435", "13437", "13439", "13465", "13467",
        "13469", "13503", "13505", "13507", "13509",
    },
    "Spandau": {
        "13581", "13583", "13585", "13587", "13589",
        "13591", "13593", "13595", "13597", "13599",
        "14089",
    },
    "Steglitz-Zehlendorf": {
        "12157", "12161", "12163", "12165", "12167",
        "12169", "12203", "12205", "12207", "12209",
        "12247", "12249", "12279", "14109", "14129",
        "14163", "14165", "14167", "14169", "14193",
        "14195",
    },
    "Treptow-Köpenick": {
        "12435", "12437", "12439", "12459", "12487",
        "12489", "12524", "12526", "12527", "12555",
        "12557", "12559", "12587", "12589",
    },
}

# PLZ zu Ortsteil (für Validierung und Anzeige)
PLZ_ORTSTEIL = {
    "10115": "Mitte", "10117": "Mitte", "10119": "Mitte",
    "10178": "Mitte", "10179": "Mitte",
    "10243": "Friedrichshain", "10245": "Friedrichshain",
    "10247": "Friedrichshain/Prenzlauer Berg",
    "10249": "Friedrichshain/Prenzlauer Berg",
    "10315": "Lichtenberg", "10317": "Lichtenberg/Rummelsburg",
    "10318": "Lichtenberg", "10319": "Lichtenberg",
    "10365": "Lichtenberg", "10367": "Lichtenberg",
    "10369": "Lichtenberg/Fennpfuhl",
    "10405": "Prenzlauer Berg", "10407": "Prenzlauer Berg",
    "10409": "Prenzlauer Berg", "10435": "Prenzlauer Berg",
    "10437": "Prenzlauer Berg", "10439": "Prenzlauer Berg/Pankow",
    "10551": "Moabit", "10553": "Moabit", "10555": "Moabit/Tiergarten",
    "10557": "Hansaviertel/Tiergarten", "10559": "Moabit",
    "10585": "Charlottenburg", "10587": "Charlottenburg",
    "10589": "Charlottenburg", "10623": "Charlottenburg",
    "10625": "Charlottenburg", "10627": "Charlottenburg",
    "10629": "Charlottenburg",
    "10707": "Wilmersdorf", "10709": "Wilmersdorf",
    "10711": "Wilmersdorf/Grunewald", "10713": "Wilmersdorf",
    "10715": "Wilmersdorf", "10717": "Wilmersdorf",
    "10719": "Wilmersdorf", "10777": "Schöneberg",
    "10779": "Schöneberg", "10781": "Schöneberg",
    "10783": "Schöneberg", "10785": "Tiergarten/Schöneberg",
    "10787": "Tiergarten", "10789": "Charlottenburg/Schöneberg",
    "10823": "Schöneberg", "10825": "Schöneberg",
    "10827": "Schöneberg", "10829": "Schöneberg",
    "10961": "Kreuzberg", "10963": "Kreuzberg/Tiergarten",
    "10965": "Kreuzberg/Neukölln", "10967": "Kreuzberg",
    "10969": "Kreuzberg", "10997": "Kreuzberg",
    "10999": "Kreuzberg",
    "12043": "Neukölln", "12045": "Neukölln",
    "12047": "Neukölln", "12049": "Neukölln",
    "12051": "Neukölln", "12053": "Neukölln",
    "12055": "Neukölln", "12057": "Neukölln",
    "12059": "Neukölln", "12099": "Neukölln/Tempelhof",
    "12101": "Tempelhof", "12103": "Tempelhof/Schöneberg",
    "12105": "Tempelhof", "12107": "Tempelhof/Mariendorf",
    "12109": "Tempelhof", "12157": "Steglitz/Schöneberg",
    "12159": "Schöneberg", "12161": "Steglitz",
    "12163": "Steglitz", "12165": "Steglitz",
    "12167": "Steglitz", "12169": "Steglitz",
    "12203": "Lichterfelde", "12205": "Lichterfelde",
    "12207": "Lichterfelde", "12209": "Lichterfelde",
    "12247": "Steglitz/Lankwitz", "12249": "Lankwitz",
    "12277": "Mariendorf/Marienfelde", "12279": "Marienfelde",
    "12305": "Buckow", "12307": "Marienfelde/Lichtenrade",
    "12309": "Lichtenrade", "12347": "Britz",
    "12349": "Britz", "12351": "Britz/Buckow/Gropiusstadt",
    "12353": "Buckow/Gropiusstadt", "12355": "Rudow",
    "12357": "Buckow/Rudow", "12359": "Britz/Rudow",
    "12435": "Treptow/Neukölln", "12437": "Baumschulenweg",
    "12439": "Niederschöneweide/Pankow", "12459": "Oberschöneweide",
    "12487": "Adlershof/Johannisthal", "12489": "Adlershof",
    "12524": "Altglienicke", "12526": "Bohnsdorf",
    "12527": "Grünau/Schmöckwitz", "12555": "Köpenick",
    "12557": "Köpenick", "12559": "Köpenick/Müggelheim",
    "12587": "Friedrichshagen", "12589": "Rahnsdorf/Treptow",
    "12619": "Hellersdorf/Kaulsdorf", "12621": "Hellersdorf",
    "12623": "Kaulsdorf/Mahlsdorf", "12627": "Hellersdorf",
    "12629": "Hellersdorf", "12679": "Marzahn",
    "12681": "Marzahn", "12683": "Biesdorf",
    "12685": "Marzahn", "12687": "Marzahn",
    "12689": "Marzahn",
    "13051": "Hohenschönhausen/Malchow", "13053": "Hohenschönhausen",
    "13055": "Hohenschönhausen", "13057": "Hohenschönhausen/Falkenberg",
    "13059": "Hohenschönhausen/Wartenberg",
    "13086": "Weißensee", "13088": "Weißensee",
    "13089": "Heinersdorf", "13125": "Buch/Karow",
    "13127": "Französisch Buchholz", "13129": "Blankenburg",
    "13156": "Rosenthal", "13158": "Rosenthal/Wilhelmsruh",
    "13159": "Blankenfelde", "13187": "Pankow",
    "13189": "Pankow", "13347": "Wedding/Gesundbrunnen",
    "13349": "Wedding", "13351": "Wedding",
    "13353": "Wedding/Moabit", "13355": "Gesundbrunnen",
    "13357": "Gesundbrunnen", "13359": "Gesundbrunnen",
    "13403": "Reinickendorf", "13405": "Reinickendorf/Tegel",
    "13407": "Reinickendorf/Wedding", "13409": "Reinickendorf",
    "13435": "Märkisches Viertel", "13437": "Märkisches Viertel",
    "13439": "Märkisches Viertel", "13465": "Frohnau/Hermsdorf",
    "13467": "Hermsdorf", "13469": "Reinickendorf/Lübars",
    "13503": "Heiligensee/Tegel", "13505": "Konradshöhe/Tegel",
    "13507": "Tegel", "13509": "Tegel/Reinickendorf",
    "13581": "Spandau", "13583": "Spandau/Falkenhagener Feld",
    "13585": "Spandau", "13587": "Hakenfelde",
    "13589": "Falkenhagener Feld", "13591": "Spandau/Staaken",
    "13593": "Spandau/Wilhelmstadt", "13595": "Wilhelmstadt",
    "13597": "Spandau", "13599": "Haselhorst/Siemensstadt",
    "13627": "Siemensstadt/Charlottenburg", "13629": "Siemensstadt",
    "14050": "Charlottenburg", "14052": "Charlottenburg",
    "14053": "Charlottenburg", "14055": "Charlottenburg/Grunewald",
    "14057": "Charlottenburg", "14059": "Charlottenburg",
    "14089": "Gatow/Kladow/Spandau",
    "14109": "Wannsee/Nikolassee", "14129": "Nikolassee/Zehlendorf",
    "14163": "Nikolassee/Zehlendorf", "14165": "Zehlendorf",
    "14167": "Lichterfelde/Zehlendorf", "14169": "Zehlendorf/Lichterfelde",
    "14193": "Grunewald/Dahlem", "14195": "Dahlem/Wilmersdorf",
    "14197": "Wilmersdorf", "14199": "Wilmersdorf/Grunewald",
}

# Alle gültigen Berliner PLZ
ALL_BERLIN_PLZ = set(PLZ_ORTSTEIL.keys())


def validate_plz(plz_input: str) -> dict:
    """
    Validiert eine PLZ-Eingabe.
    Returns: {"valid": [...], "invalid": [...]}
    """
    plz_list = [p.strip() for p in plz_input.replace(" ", "").split(",")]
    valid = []
    invalid = []
    for plz in plz_list:
        if not plz:
            continue
        if len(plz) != 5 or not plz.isdigit():
            invalid.append({"plz": plz, "reason": "muss 5 Ziffern haben"})
        elif plz not in ALL_BERLIN_PLZ:
            invalid.append({"plz": plz, "reason": "keine bekannte Berliner PLZ"})
        else:
            valid.append({"plz": plz, "ortsteil": PLZ_ORTSTEIL[plz]})
    return {"valid": valid, "invalid": invalid}


def plz_matches_filter(listing_plz: str, filter_type: str, filter_value) -> bool:
    """
    Prüft ob eine Wohnungs-PLZ zum Filter des Nutzers passt.
    filter_type: "ring" | "plz" | "bezirk"
    filter_value: None | list of PLZ | list of Bezirke
    """
    if not listing_plz:
        return True  # Kein PLZ bekannt → anzeigen

    if filter_type == "ring":
        return listing_plz in INNERHALB_RING

    if filter_type == "plz":
        return listing_plz in set(filter_value)

    if filter_type == "bezirk":
        for bezirk in filter_value:
            if bezirk in BEZIRK_PLZ and listing_plz in BEZIRK_PLZ[bezirk]:
                return True
        return False

    return True
