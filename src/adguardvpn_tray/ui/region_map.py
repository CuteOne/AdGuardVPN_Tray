CONTINENT_ORDER = ["North America", "Europe", "Asia", "South America", "Africa", "Oceania", "Other"]

_ISO_TO_CONTINENT = {
    "US": "North America", "CA": "North America", "MX": "North America",
    "AR": "South America", "BR": "South America", "CL": "South America",
    "CO": "South America", "PE": "South America",
    "AT": "Europe", "BE": "Europe", "BG": "Europe", "CH": "Europe", "CY": "Europe",
    "CZ": "Europe", "DE": "Europe", "DK": "Europe", "EE": "Europe", "ES": "Europe",
    "FI": "Europe", "FR": "Europe", "GB": "Europe", "GR": "Europe", "HR": "Europe",
    "HU": "Europe", "IE": "Europe", "IT": "Europe", "LT": "Europe", "LU": "Europe",
    "LV": "Europe", "MD": "Europe", "NL": "Europe", "NO": "Europe", "PL": "Europe",
    "PT": "Europe", "RO": "Europe", "RS": "Europe", "RU": "Europe", "SE": "Europe",
    "SK": "Europe", "UA": "Europe",
    "AE": "Asia", "CN": "Asia", "HK": "Asia", "ID": "Asia", "IL": "Asia", "IN": "Asia",
    "JP": "Asia", "KH": "Asia", "KR": "Asia", "KZ": "Asia", "NP": "Asia", "PH": "Asia",
    "SG": "Asia", "TH": "Asia", "TR": "Asia", "TW": "Asia", "VN": "Asia",
    "EG": "Africa", "NG": "Africa", "ZA": "Africa",
    "AU": "Oceania", "NZ": "Oceania",
}


def continent_for(iso: str) -> str:
    return _ISO_TO_CONTINENT.get(iso.upper(), "Other")
