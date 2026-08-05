from __future__ import annotations

import re

from .i18n import tr
from .models import Region


COUNTRIES: dict[str, tuple[str, str]] = {
    "AD": ("Andorra", "Andorra"), "AE": ("United Arab Emirates", "Vereinigte Arabische Emirate"),
    "AL": ("Albania", "Albanien"), "AM": ("Armenia", "Armenien"),
    "AR": ("Argentina", "Argentinien"), "AT": ("Austria", "Österreich"),
    "AU": ("Australia", "Australien"), "BA": ("Bosnia and Herzegovina", "Bosnien und Herzegowina"),
    "BD": ("Bangladesh", "Bangladesch"), "BE": ("Belgium", "Belgien"),
    "BG": ("Bulgaria", "Bulgarien"), "BO": ("Bolivia", "Bolivien"),
    "BR": ("Brazil", "Brasilien"), "BS": ("Bahamas", "Bahamas"),
    "CA": ("Canada", "Kanada"), "CH": ("Switzerland", "Schweiz"),
    "CL": ("Chile", "Chile"), "CN": ("China", "China"),
    "CO": ("Colombia", "Kolumbien"), "CR": ("Costa Rica", "Costa Rica"),
    "CY": ("Cyprus", "Zypern"), "CZ": ("Czechia", "Tschechien"),
    "DE": ("Germany", "Deutschland"), "DK": ("Denmark", "Dänemark"),
    "DZ": ("Algeria", "Algerien"), "EC": ("Ecuador", "Ecuador"),
    "EE": ("Estonia", "Estland"), "EG": ("Egypt", "Ägypten"),
    "ES": ("Spain", "Spanien"), "FI": ("Finland", "Finnland"),
    "FR": ("France", "Frankreich"), "GB": ("United Kingdom", "Vereinigtes Königreich"),
    "GE": ("Georgia", "Georgien"), "GL": ("Greenland", "Grönland"),
    "GR": ("Greece", "Griechenland"), "GT": ("Guatemala", "Guatemala"),
    "HK": ("Hong Kong", "Hongkong"), "HR": ("Croatia", "Kroatien"),
    "HU": ("Hungary", "Ungarn"), "ID": ("Indonesia", "Indonesien"),
    "IE": ("Ireland", "Irland"), "IL": ("Israel", "Israel"),
    "IM": ("Isle of Man", "Isle of Man"), "IN": ("India", "Indien"),
    "IS": ("Iceland", "Island"), "IT": ("Italy", "Italien"),
    "JP": ("Japan", "Japan"), "KH": ("Cambodia", "Kambodscha"),
    "KR": ("South Korea", "Südkorea"), "KZ": ("Kazakhstan", "Kasachstan"),
    "LI": ("Liechtenstein", "Liechtenstein"), "LK": ("Sri Lanka", "Sri Lanka"),
    "LT": ("Lithuania", "Litauen"), "LU": ("Luxembourg", "Luxemburg"),
    "LV": ("Latvia", "Lettland"), "MA": ("Morocco", "Marokko"),
    "MC": ("Monaco", "Monaco"), "MD": ("Moldova", "Moldau"),
    "ME": ("Montenegro", "Montenegro"), "MK": ("North Macedonia", "Nordmazedonien"),
    "MN": ("Mongolia", "Mongolei"), "MO": ("Macao", "Macau"),
    "MT": ("Malta", "Malta"), "MX": ("Mexico", "Mexiko"),
    "MY": ("Malaysia", "Malaysia"), "NG": ("Nigeria", "Nigeria"),
    "NL": ("Netherlands", "Niederlande"), "NO": ("Norway", "Norwegen"),
    "NP": ("Nepal", "Nepal"), "NZ": ("New Zealand", "Neuseeland"),
    "PA": ("Panama", "Panama"), "PE": ("Peru", "Peru"),
    "PH": ("Philippines", "Philippinen"), "PL": ("Poland", "Polen"),
    "PT": ("Portugal", "Portugal"), "QA": ("Qatar", "Katar"),
    "RO": ("Romania", "Rumänien"), "RS": ("Serbia", "Serbien"),
    "SA": ("Saudi Arabia", "Saudi-Arabien"), "SE": ("Sweden", "Schweden"),
    "SG": ("Singapore", "Singapur"), "SI": ("Slovenia", "Slowenien"),
    "SK": ("Slovakia", "Slowakei"), "TR": ("Turkey", "Türkei"),
    "TW": ("Taiwan", "Taiwan"), "UA": ("Ukraine", "Ukraine"),
    "US": ("United States", "USA"), "UY": ("Uruguay", "Uruguay"),
    "VE": ("Venezuela", "Venezuela"), "VN": ("Vietnam", "Vietnam"),
    "ZA": ("South Africa", "Südafrika"),
}

PREFIX_CODES = {
    "US": "US", "CA": "CA", "AU": "AU", "DE": "DE", "NL": "NL",
    "UK": "GB", "ES": "ES", "FI": "FI", "IT": "IT", "JP": "JP",
    "SE": "SE", "DK": "DK", "CH": "CH", "AT": "AT", "FR": "FR",
    "SG": "SG", "BR": "BR", "BE": "BE", "KR": "KR", "NZ": "NZ",
    "MX": "MX", "PL": "PL", "AR": "AR", "IL": "IL", "ZA": "ZA",
    "HU": "HU", "LT": "LT", "PT": "PT", "TW": "TW", "SK": "SK",
    "CL": "CL", "LU": "LU", "RS": "RS", "RO": "RO",
}

OFFICIAL_COUNTRY_NAMES: dict[str, str] = {
    "Panama": "PA", "Kazakhstan": "KZ", "Mongolia": "MN", "Cambodia": "KH",
    "Hong Kong": "HK", "India": "IN", "Morocco": "MA", "Bangladesh": "BD",
    "Bolivia": "BO", "Ukraine": "UA", "Sri Lanka": "LK", "Uruguay": "UY",
    "Bahamas": "BS", "Peru": "PE", "Guatemala": "GT", "Venezuela": "VE",
    "Costa Rica": "CR", "Ecuador": "EC", "Macao": "MO", "Vietnam": "VN",
    "Nepal": "NP", "Albania": "AL", "Algeria": "DZ", "Andorra": "AD",
    "Argentina": "AR", "Armenia": "AM", "Austria": "AT", "Belgium": "BE",
    "Bosnia and Herzegovina": "BA", "Brazil": "BR", "Bulgaria": "BG",
    "Chile": "CL", "China": "CN", "Colombia": "CO", "Croatia": "HR",
    "Czech Republic": "CZ", "Denmark": "DK", "Egypt": "EG", "Estonia": "EE",
    "France": "FR", "Georgia": "GE", "Greece": "GR", "Greenland": "GL",
    "Hungary": "HU", "Iceland": "IS", "Indonesia": "ID", "Ireland": "IE",
    "Isle of Man": "IM", "Israel": "IL", "Latvia": "LV", "Liechtenstein": "LI",
    "Lithuania": "LT", "Luxembourg": "LU", "Malaysia": "MY", "Malta": "MT",
    "Mexico": "MX", "Moldova": "MD", "Monaco": "MC", "Montenegro": "ME",
    "New Zealand": "NZ", "Nigeria": "NG", "North Macedonia": "MK", "Norway": "NO",
    "Philippines": "PH", "Poland": "PL", "Portugal": "PT", "Qatar": "QA",
    "Romania": "RO", "Saudi Arabia": "SA", "Serbia": "RS", "Singapore": "SG",
    "Slovakia": "SK", "Slovenia": "SI", "South Africa": "ZA", "South Korea": "KR",
    "Switzerland": "CH", "Taiwan": "TW", "Turkey": "TR", "United Arab Emirates": "AE",
}

# Keep the explicit aliases above (for example “Czech Republic”), then
# automatically cover every canonical English country name from COUNTRIES.
OFFICIAL_COUNTRY_NAMES = {
    **{english_name: code for code, (english_name, _) in COUNTRIES.items()},
    **OFFICIAL_COUNTRY_NAMES,
}


SPECIAL_LOCATIONS = {
    "en": {"East": "East", "West": "West", "South West": "South West"},
    "de": {"East": "Ost", "West": "West", "South West": "Südwesten"},
}


def country_name(code: str, language_code: str) -> str:
    pair = COUNTRIES.get(code.upper())
    if not pair:
        return code.upper()
    return pair[1] if language_code == "de" else pair[0]


def localized_region_name(region: Region, language_code: str) -> str:
    name = region.name.strip()
    streaming = name.endswith(" Streaming Optimized")
    if streaming:
        name = name[:-len(" Streaming Optimized")].strip()

    prefix_match = re.match(r"^([A-Z]{2})\s+(.+)$", name)
    if name in PREFIX_CODES:
        result = country_name(PREFIX_CODES[name], language_code)
    elif prefix_match and prefix_match.group(1) in PREFIX_CODES:
        prefix, location = prefix_match.groups()
        code = PREFIX_CODES[prefix]
        country = country_name(code, language_code)
        official_country = country_name(code, "en")
        if location in {official_country, "Netherlands", "Germany", "Australia"}:
            result = country
        else:
            location = SPECIAL_LOCATIONS.get(language_code, {}).get(location, location)
            result = f"{country} – {location}"
    elif name in OFFICIAL_COUNTRY_NAMES:
        result = country_name(OFFICIAL_COUNTRY_NAMES[name], language_code)
    else:
        result = name

    if streaming:
        stream_text = "Streaming-optimiert" if language_code == "de" else "Streaming optimized"
        result = f"{result} – {stream_text}"
    return result


def region_display_name(region: Region, language_code: str) -> str:
    name = localized_region_name(region, language_code)
    if region.geo:
        suffix = "virtueller Standort" if language_code == "de" else "virtual location"
        name += f" ({suffix})"
    if region.ping_ms is None:
        return f"{name} · {tr('common.not_reachable')}"
    return f"{name} · {region.ping_ms:.0f} ms"


def search_haystack(region: Region) -> str:
    return " ".join([
        region.region_id,
        region.name,
        localized_region_name(region, "en"),
        localized_region_name(region, "de"),
    ]).casefold()


def public_country_name(code: str, language_code: str) -> str:
    code = code.strip().upper()
    if not code:
        return tr("common.unknown")
    name = country_name(code, language_code)
    return f"{name} ({code})" if name != code else code
